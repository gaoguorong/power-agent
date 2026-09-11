# -*- coding: utf-8 -*-
"""
GraphAgent 单例服务：驱动编译后的 LangGraph 图，把逐节点产出转成 SSE 事件给前端。

编译图状态机：START → agent →（有 tool_calls ? inject_session → tools
→ skill_check → agent）* → END

为什么用 graph.astream(stream_mode="updates") 而不是 ainvoke 一把梭？
因为要在每一步中间插播 tool_start / tool_end 事件，前端靠它们渲染
"AI 正在做什么"。astream 逐节点产出更新，服务层把更新转成与手动循环
完全一致的事件序列。消息历史自己存（_session_messages 内存字典），
页面刷新恢复聊天直接读它即可。
"""
import json
import asyncio
import math
import traceback
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from agents.graph_agent import GraphAgent
from executors.base import ToolExecutionRequest
from executors.registry import build_default_registry
from schemas.tool_result import normalize_tool_result
from tools import langchain_tool
from tools.langchain_tool import ALL_TOOLS
from skills.skill_runner import (match_skill, match_skill_after_llm,
                                   run_overload_relief, run_load_sweep)

from graph_util import  _fill_tool_run, _sanitize_non_finite, _parse_json_if_possible, _message_to_persist, _persist_to_message, _messages_to_frontend_format,_safe_preview

# 单次聊天内最多允许多少轮「LLM思考 → 调工具」，防止异常情况下死循环
MAX_TOOL_ROUNDS = 10

# 编译图递归步数上限：一轮工具循环 = agent + inject_session + tools + skill_check
# 共 4 个节点，MAX_TOOL_ROUNDS 轮后再留一次收尾 agent 的余量
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 4 + 5

# Skill 快速通道的哨兵：编排引擎接管并完成本回合后产出，告知上层无需再走 LLM 流程
_SKILL_DONE = object()


class GraphService:
    """全进程单例，包装唯一的 GraphAgent，提供聊天与电网状态查询。

    用法：GraphService.get_instance()
    """

    _instance: Optional["GraphService"] = None

    @classmethod
    def get_instance(cls) -> "GraphService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._graph_agent = GraphAgent(
            tools_node=self._tools_node,
            skill_check_node=self._skill_check_node
        )
        self._tools_by_name = {t.name: t for t in ALL_TOOLS}
        self._registry = build_default_registry()
        # session_id → 完整消息历史（页面刷新恢复聊天的唯一数据源）
        self._session_messages: Dict[str, List[BaseMessage]] = {}

        print("[GraphService] 已就绪，消息历史存进程内存（重启丢失）")

    # ==============================================================
    # 0. 服务图的两个注入节点（由 build_service_graph 编译进正式链路）
    # ==============================================================
    def _tools_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """tools 节点：执行上一轮 LLM 决定的工具调用（替代预置 ToolNode）。

        必须走 _execute_tools 而不是 ToolNode，保住「注册表 → LangChain 兜底
        → 未知工具」的双通道调度与超时防护。
        """
        last_msg = state["messages"][-1]
        if not (isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None)):
            return {}
        return {"messages": self._execute_tools(last_msg.tool_calls)}

    def _skill_check_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """skill_check 节点：每轮工具执行完检查后置技能。

        命中则写入 matched_skill，条件边据此直接 END，由服务层接管跑确定性
        编排闭环，避免 LLM 再空跑一轮；未命中（None）走回 agent 继续。
        """
        gt = langchain_tool.get_gt_obj(state.get("session_id", "default"))
        skill = match_skill_after_llm(state.get("question", ""), gt)
        return {"matched_skill": skill}

    # ==============================================================
    # 1. 流式聊天：驱动编译图逐节点产出，转成 SSE 事件
    #    前端会收到：welcome → tool_start/tool_end(若干) → token → done
    # ==============================================================

    async def chat_stream(
        self,
        session_id: str,
        question: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        cfg = {"configurable": {"thread_id": session_id},
               "recursion_limit": RECURSION_LIMIT}
        state: Dict[str, Any] = {
            # 历史消息 + 本轮新问题（多轮对话不丢上下文）
            "messages": list(self._session_messages.get(session_id, []))
                        + [HumanMessage(content=question)],
            "session_id": session_id,
            "question": question,
        }

        msgs: List[BaseMessage] = state["messages"]
        tool_runs: List[Dict[str, Any]] = []

        yield {"event": "welcome", "data": {"session_id": session_id, "question": question}}

        try:
            # ===== Skill 快速通道：LLM 决策前先做意图匹配（图外，原样保留）=====

            skill_done = False
            async for ev in self._run_skill_channel(session_id, question, state, tool_runs):
                if ev is _SKILL_DONE:
                    skill_done = True
                    continue
                yield ev
            if skill_done:
                return

            # ===== 编译图主循环：逐节点更新 → 与手动循环完全一致的 SSE =====
            async for chunk in self._compiled.astream(state, config=cfg, stream_mode="updates" ):
                for node_name, update in chunk.items():
                    if node_name == "agent":
                        ai_msg = update["messages"][-1]
                        msgs.append(ai_msg)

                        # LLM 无工具调用 = 本回合收尾；先查后置 Skill
                        # （命中则插播闭环），否则输出最终回答
                        if not getattr(ai_msg, "tool_calls", None):
                            gt = langchain_tool.get_gt_obj(session_id)
                            after_skill = await asyncio.to_thread(
                                match_skill_after_llm, question, gt)
                            if after_skill is not None:
                                async for ev in self._run_skill_channel(
                                        session_id, question, {"messages": msgs}, tool_runs,
                                        pre_matched_skill=after_skill):
                                    if ev is _SKILL_DONE:
                                        return
                                    yield ev
                                return

                            text = (ai_msg.content or "").strip()
                            self._save_messages(session_id, {"messages": msgs})
                            if text:
                                yield {"event": "token", "data": {"text": text}}
                            yield {"event": "done",
                                   "data": {"ai_text": text, "tool_runs": tool_runs}}
                            return

                        # 有工具调用：先告诉前端这轮要调哪些工具
                        # （session_id 由图内 inject_session 节点随后注入 args）
                        for tc in ai_msg.tool_calls:
                            args = tc.get("args") or {}
                            tool_runs.append({"name": tc["name"], "input": args,
                                              "output": None, "status": "running",
                                              # 内部字段：按 tool_call_id 精确回填结果
                                              "_call_id": tc.get("id", "")})
                            yield {"event": "tool_start", "data": {
                                "name": tc["name"],
                                "input": _safe_preview(args),
                                "run_id": tc.get("id", ""),
                            }}

                    elif node_name == "tools":
                        # 工具执行完：回填结果 + 播报 tool_end
                        for tm in update["messages"]:
                            msgs.append(tm)
                            output = _parse_json_if_possible(tm.content)
                            _fill_tool_run(tool_runs, tm.name, output,
                                           getattr(tm, "tool_call_id", ""))
                            yield {"event": "tool_end", "data": {
                                "name": tm.name,
                                "output_preview": _safe_preview(output, 200),
                            }}

                    elif node_name == "skill_check":
                        # 后置技能命中：图在此直接 END，服务层接管跑确定性闭环
                        matched = update.get("matched_skill")
                        if matched is not None:
                            async for ev in self._run_skill_channel(
                                    session_id, question, {"messages": msgs}, tool_runs,
                                    pre_matched_skill=matched):
                                if ev is _SKILL_DONE:
                                    return
                                yield ev
                            return
            # 图正常耗尽但没走上面的分支——正常流程到不了这里（agent 无工具调用
            # 时已 return），仅作兜底
            self._save_messages(session_id, {"messages": msgs})
            yield {"event": "done", "data": {"ai_text": "", "tool_runs": tool_runs,
                                             "warning": "max_rounds"}}

        except GraphRecursionError:
            # 超过递归上限（等价于原 MAX_TOOL_ROUNDS 兜底）
            self._save_messages(session_id, {"messages": msgs})
            yield {"event": "done", "data": {"ai_text": "", "tool_runs": tool_runs,
                                             "warning": "max_rounds"}}
        except Exception as exc:
            self._save_messages(session_id, {"messages": msgs})
            yield {"event": "error", "data": {
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=5),
            }}

    async def _run_skill_channel(
        self,
        session_id: str,
        question: str,
        state: Dict[str, Any],
        tool_runs: List[Dict[str, Any]],
        pre_matched_skill: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Any, None]:
        """Skill 快速通道：命中且前置满足时，跑确定性编排闭环并逐步产出 SSE 事件。

        - 未命中 / 电网尚未建立：不产出任何事件直接返回，让上层回退到 agent_node 正常流程；
        - 命中并接管：把编排引擎每步工具执行转成 tool_start/tool_end，过程按标准结构写回
          state（AIMessage(tool_calls) + ToolMessage + 结论），最后产出 token/done，并以
          _SKILL_DONE 哨兵告知上层“本回合已结束，无需再走 LLM”。
        """
        skill = pre_matched_skill if pre_matched_skill is not None else match_skill(question)
        if skill is None:
            return
        gt = langchain_tool.get_gt_obj(session_id)
        if pre_matched_skill is None and getattr(gt, "net", None) is None:
            return

        # 按技能名分发到对应执行器（均为同步 generator，事件协议一致）
        runner = run_overload_relief
        if skill.get("name") == "load_sweep":
            runner = run_load_sweep

        tool_calls: List[Dict[str, Any]] = []
        tool_msgs: List[ToolMessage] = []
        final_text = ""
        seq = 0

        def _safe_next() -> Optional[Dict[str, Any]]:
            try:
                return next(gen)
            except StopIteration:
                return None

        gen = runner(gt, skill)
        while True:
            ev = await asyncio.to_thread(_safe_next)
            if ev is None:
                break

            kind = ev.get("kind")
            if kind == "tool":
                seq += 1
                name = ev.get("name", "")
                inp = ev.get("input", {}) or {}
                out = _sanitize_non_finite(ev.get("output", {}))
                call_id = f"skill-{seq}"
                # 实时 SSE：让前端看到“正在做什么”
                tool_runs.append({"name": name, "input": inp, "output": None,
                                  "status": "running", "_call_id": call_id})
                yield {"event": "tool_start", "data": {
                    "name": name, "input": _safe_preview(inp), "run_id": call_id}}
                _fill_tool_run(tool_runs, name, out, call_id)
                yield {"event": "tool_end", "data": {
                    "name": name, "output_preview": _safe_preview(out, 200)}}
                # 标准消息结构：供刷新恢复 / 持久化 / 多轮上下文
                tool_calls.append({"name": name, "args": inp, "id": call_id, "type": "tool_call"})
                tool_msgs.append(ToolMessage(
                    content=json.dumps(out, ensure_ascii=False, default=str),
                    name=name, tool_call_id=call_id))

            elif kind == "final":
                if ev.get("aborted"):
                    return  # 前置不足，回退（不接管本回合）
                final_text = ev.get("text", "") or ""

        # 收尾：整个 skill 回合按“一条 AIMessage(全部工具调用) + 全部 ToolMessage + 结论”写回，
        # 与正常工具循环的历史结构一致，_messages_to_frontend_format 恢复时才能正确聚合。
        if tool_calls:
            state["messages"].append(AIMessage(content="", tool_calls=tool_calls))
            state["messages"].extend(tool_msgs)
        if final_text:
            state["messages"].append(AIMessage(content=final_text))
        self._save_messages(session_id, state)

        if final_text:
            yield {"event": "token", "data": {"text": final_text}}
        yield {"event": "done", "data": {"ai_text": final_text, "tool_runs": tool_runs}}
        yield _SKILL_DONE

    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolMessage]:
        """逐个执行工具，结果统一为标准结构再包 ToolMessage。

        调度顺序：注册表优先 → 未登记的回退到 LangChain 工具 → 都没有才算未知工具。
        注册表通道自带超时等防护；回退通道保持原行为，兼容未迁移的工具。
        """
        results: List[ToolMessage] = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}

            entry = self._registry.get(name)
            if entry is not None:
                # 已注册：走适配器统一通道，超时取注册表里登记的值
                definition, _adapter = entry
                normalized = self._registry.execute(ToolExecutionRequest(
                    tool_id=name,
                    parameters=args,
                    timeout_seconds=definition.timeout_seconds,
                ))
            else:
                # 未注册：回退老路（LangChain 工具），行为与接入前完全一致
                tool = self._tools_by_name.get(name)
                if tool is None:
                    normalized = normalize_tool_result(
                        RuntimeError(f"未知工具 '{name}'"), name)
                else:
                    try:
                        raw = tool.invoke(args)
                    except Exception as exc:
                        raw = exc  # 异常交给 normalize 统一翻译
                    normalized = normalize_tool_result(raw, name)

            # 清洗 NaN/Infinity：Starlette 的 JSONResponse 用 allow_nan=False，
            # 非有限浮点会让刷新恢复历史时序列化报 ValueError
            normalized = _sanitize_non_finite(normalized)
            text = json.dumps(normalized, ensure_ascii=False, indent=2, default=str)
            results.append(ToolMessage(content=text, name=name, tool_call_id=tc.get("id", "")))
        return results

    def _save_messages(self, session_id: str, state: Dict[str, Any]) -> None:
        """把最新消息历史存进内存字典（刷新页面时 get_session_messages 能拿到）"""
        try:
            self._session_messages[session_id] = list(state["messages"])
        except Exception:
            pass

    # ==============================================================
    # 2. 消息历史查询（页面刷新恢复聊天记录用）
    # ==============================================================

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """返回该会话的完整消息历史（前端可渲染格式）。
        聚合成和 SSE 流式结束时一致的形状：
        每条 user 消息后跟一条 assistant 消息（工具调用合并进 tool_runs），
        这样点历史会话恢复出来的界面和实时聊天时看到的一样。
        """
        return _messages_to_frontend_format(
            self._session_messages.get(session_id, [])
        )

    # ==============================================================
    # 2.5 消息历史持久化：内存 ⇄ MySQL（重启后恢复聊天记录靠它）
    # ==============================================================

    def has_session_messages(self, session_id: str) -> bool:
        """内存里有没有该会话的消息历史"""
        return bool(self._session_messages.get(session_id))

    def dump_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """把内存中的消息历史序列化成可存 JSON 的结构"""
        return [_message_to_persist(m)
                for m in self._session_messages.get(session_id, [])
                if isinstance(m, BaseMessage)]

    def restore_session_messages(self, session_id: str, items: List[Dict[str, Any]]) -> None:
        """从持久化数据恢复消息历史到内存（还原成 LangChain Message 对象）"""
        msgs = []
        for it in items:
            try:
                m = _persist_to_message(it)
            except Exception:
                m = None
            if m is not None:
                msgs.append(m)
        if msgs:
            self._session_messages[session_id] = msgs

    # ==============================================================
    # 3. 电网对象状态管理
    #    电网实例真正存放在 langchain_tool 模块的全局 _sessions 字典里，
    #    这里只是给 session_service 提供统一的查询/清理入口。
    # ==============================================================

    @staticmethod
    def _grid_sessions() -> Dict[str, Any]:
        return getattr(langchain_tool, "_sessions", {})

    def has_grid_session(self, session_id: str) -> bool:
        """该会话内存里有没有已创建的电网对象"""
        return session_id in self._grid_sessions()

    def reset_grid_session(self, session_id: str) -> None:
        """清掉该会话的电网对象（下次调工具会自动重建）"""
        self._grid_sessions().pop(session_id, None)

    def get_session_grid_meta(self, session_id: str) -> Dict[str, Any]:
        """从内存电网对象提取恢复元信息，供 session_service 存 MySQL：

        last_grid_type  电网类型（靠 _patched_grid_type 补丁属性记录）
        load_factor     负荷倍率 = 当前总负荷 / 原始总负荷
        has_pf_result   是否已跑过潮流
        """
        gt = self._grid_sessions().get(session_id)
        if gt is None:
            return {}
        meta: Dict[str, Any] = {}

        grid_type = getattr(gt, "_patched_grid_type", None)
        if grid_type:
            meta["last_grid_type"] = grid_type

        # 文件加载的真实电网：记录来源路径，重启后按路径重新加载
        grid_file = getattr(gt, "_patched_grid_file", None) or getattr(gt, "_source_file", None)
        if grid_file:
            meta["last_grid_file"] = grid_file

        try:
            net = getattr(gt, "net", None)
            orig_p = getattr(gt, "_load_original_p_mw", None)
            if net is not None and orig_p is not None and len(orig_p) > 0:
                orig_sum = float(orig_p.sum())
                if orig_sum > 1e-6:
                    meta["load_factor"] = round(float(net.load["p_mw"].sum()) / orig_sum, 4)
        except Exception:
            pass

        net = getattr(gt, "net", None)
        if net is not None and hasattr(net, "res_bus") and len(net.res_bus) > 0:
            meta["has_pf_result"] = True

        return meta
