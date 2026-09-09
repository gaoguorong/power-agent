# -*- coding: utf-8 -*-
"""
GraphAgent 单例服务：手动逐步驱动状态机，产出 SSE 事件给前端。

状态机：START → agent →（有 tool_calls ? inject_session → tools → agent）* → END

为什么不用 LangGraph 的 graph.ainvoke 一把梭？
因为要在每一步中间插播 tool_start / tool_end 事件，前端靠它们渲染
"AI 正在做什么"。所以这里手动逐节点执行，消息历史也自己存
（_session_messages 内存字典），页面刷新恢复聊天直接读它即可。
"""
import json
import asyncio
import math
import traceback
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage

from agents.graph_agent import GraphAgent
from executors.base import ToolExecutionRequest
from executors.registry import build_default_registry
from schemas.tool_result import normalize_tool_result
from tools import langchain_tool
from tools.langchain_tool import ALL_TOOLS
from skills.skill_runner import match_skill, run_overload_relief

# 单次聊天内最多允许多少轮「LLM思考 → 调工具」，防止异常情况下死循环
MAX_TOOL_ROUNDS = 10

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
        self._graph_agent = GraphAgent()
        # 工具按名字索引，未注册工具的兜底执行通道用
        self._tools_by_name = {t.name: t for t in ALL_TOOLS}
        # 工具注册表：已登记的工具优先走适配器统一通道（带超时等防护）
        self._registry = build_default_registry()
        # session_id → 完整消息历史（页面刷新恢复聊天的唯一数据源）
        self._session_messages: Dict[str, List[BaseMessage]] = {}
        print("[GraphService] 已就绪，消息历史存进程内存（重启丢失）")

    # ==============================================================
    # 1. 流式聊天：手动驱动状态机，逐条 yield SSE 事件
    #    前端会收到：welcome → tool_start/tool_end(若干) → token → done
    # ==============================================================

    async def chat_stream(
        self,
        session_id: str,
        question: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        graph_agent = self._graph_agent
        cfg = {"configurable": {"thread_id": session_id}}
        state: Dict[str, Any] = {
            # 历史消息 + 本轮新问题（多轮对话不丢上下文）
            "messages": list(self._session_messages.get(session_id, []))
                        + [HumanMessage(content=question)],
            "session_id": session_id,
        }
        tool_runs: List[Dict[str, Any]] = []

        yield {"event": "welcome", "data": {"session_id": session_id, "question": question}}

        try:
            # ===== Skill 快速通道：LLM 决策前先做意图匹配 =====
            # 命中且电网已建时，直接跑确定性编排闭环（绕过 LLM 逐工具决策）；
            # 未命中/前置不足/异常，都优雅回退到下面的 agent_node 正常流程。
            skill_done = False
            async for ev in self._run_skill_channel(session_id, question, state, tool_runs):
                if ev is _SKILL_DONE:
                    skill_done = True
                    continue
                yield ev
            if skill_done:
                return

            for _ in range(MAX_TOOL_ROUNDS):
                # 1) LLM 决策：要么直接回答，要么给出要调用的工具清单
                ai_msg = await asyncio.to_thread(graph_agent.agent_node, state)
                ai_msg = ai_msg["messages"][-1]
                state["messages"].append(ai_msg)

                # 2) 没有 tool_calls = 最终回答，收尾
                if not getattr(ai_msg, "tool_calls", None):
                    text = (ai_msg.content or "").strip()
                    self._save_messages(session_id, state)
                    if text:
                        yield {"event": "token", "data": {"text": text}}
                    yield {"event": "done", "data": {"ai_text": text, "tool_runs": tool_runs}}
                    return

                # 3) 先告诉前端：这轮要调哪些工具
                for tc in ai_msg.tool_calls:
                    args = tc.get("args") or {}
                    tool_runs.append({"name": tc["name"], "input": args,
                                      "output": None, "status": "running",
                                      # 内部字段：按 tool_call_id 精确回填结果，前端用不到但无害
                                      "_call_id": tc.get("id", "")})
                    yield {"event": "tool_start", "data": {
                        "name": tc["name"],
                        "input": _safe_preview(args),
                        "run_id": tc.get("id", ""),
                    }}

                # 4) 把 session_id 注入每个工具的 args（多会话电网隔离靠它）
                await asyncio.to_thread(graph_agent.inject_session_node, state, cfg)

                # 5) 真正执行工具，结果回填给状态机 + 播报给前端
                tool_msgs = await asyncio.to_thread(self._execute_tools, ai_msg.tool_calls)
                state["messages"].extend(tool_msgs)
                for tm in tool_msgs:
                    output = _parse_json_if_possible(tm.content)
                    _fill_tool_run(tool_runs, tm.name, output,
                                   getattr(tm, "tool_call_id", ""))
                    yield {"event": "tool_end", "data": {
                        "name": tm.name,
                        "output_preview": _safe_preview(output, 200),
                    }}

            # 超过最大轮数强制结束（正常流程到不了这里，只是兜底）
            self._save_messages(session_id, state)
            yield {"event": "done", "data": {"ai_text": "", "tool_runs": tool_runs,
                                             "warning": "max_rounds"}}

        except Exception as exc:
            self._save_messages(session_id, state)
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
    ) -> AsyncGenerator[Any, None]:
        """Skill 快速通道：命中且前置满足时，跑确定性编排闭环并逐步产出 SSE 事件。

        - 未命中 / 电网尚未建立：不产出任何事件直接返回，让上层回退到 agent_node 正常流程；
        - 命中并接管：把编排引擎每步工具执行转成 tool_start/tool_end，过程按标准结构写回
          state（AIMessage(tool_calls) + ToolMessage + 结论），最后产出 token/done，并以
          _SKILL_DONE 哨兵告知上层“本回合已结束，无需再走 LLM”。
        """
        skill = match_skill(question)
        if skill is None:
            return
        gt = langchain_tool.get_gt_obj(session_id)
        if getattr(gt, "net", None) is None:
            # 前置不足：还没建电网（要先建网/断线，需 LLM 解析参数），交回正常流程
            return

        tool_calls: List[Dict[str, Any]] = []
        tool_msgs: List[ToolMessage] = []
        final_text = ""
        seq = 0

        gen = run_overload_relief(gt, skill)
        while True:
            try:
                # 编排引擎是同步 generator（内含阻塞的 runpp），逐步放线程池推进，
                # 既不卡事件循环，又能把每一步实时下发前端。
                ev = await asyncio.to_thread(next, gen)
            except StopIteration:
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


# ==============================================================
# 模块内小工具函数
# ==============================================================

def _msg_role(m: BaseMessage) -> str:
    """LangChain Message 类型 → 前端认识的 role 字符串"""
    if isinstance(m, HumanMessage):
        return "user"
    if isinstance(m, AIMessage):
        return "assistant"
    if isinstance(m, ToolMessage):
        return "tool"
    return type(m).__name__.lower()


def _fill_tool_run(tool_runs: List[Dict[str, Any]], name: str, output: Any,
                   call_id: str = "") -> None:
    """把执行结果回填到 tool_runs 里对应的 running 记录。

    优先按 tool_call_id 精确配对：同一工具在一轮里被并行调用多次时（如连续
    load_grid_from_file 两个文件），只按名字配对会把结果填错块（输入 .json
    却显示加载了 .p）。call_id 缺失时才退回按名字配对最近一条 running。
    """
    if call_id:
        for run in reversed(tool_runs):
            if run.get("_call_id") == call_id and run["status"] == "running":
                run["output"] = _safe_preview(output)
                run["status"] = "ok"
                return
    for run in reversed(tool_runs):
        if run["name"] == name and run["status"] == "running":
            run["output"] = _safe_preview(output)
            run["status"] = "ok"
            return


def _sanitize_non_finite(obj: Any) -> Any:
    """递归把 NaN / Infinity 等非有限浮点替换成 None。

    工具结果里偶尔会算出 NaN（如孤立线路的负载率均值），Python json.dumps
    默认会把它写成字面量 NaN 存起来；刷新恢复历史时 FastAPI 的 JSONResponse
    （allow_nan=False）再序列化就会抛 ValueError。统一在边界清洗成 None。
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


def _parse_json_if_possible(text: Any) -> Any:
    """工具输出是 JSON 字符串就解析成 dict（前端展示更好看），否则原样返回。
    解析后统一清洗 NaN/Infinity，兼容数据库里已存了 NaN 字面量的历史记录。"""
    if isinstance(text, str):
        try:
            return _sanitize_non_finite(json.loads(text))
        except Exception:
            return text
    return _sanitize_non_finite(text)


def _safe_preview(obj: Any, max_len: int = 300) -> str:
    """任意对象 → 短字符串预览（前端气泡展示用，避免大 JSON 塞爆页面）"""
    try:
        if obj is None:
            return ""
        if isinstance(obj, str):
            text = obj
        elif isinstance(obj, (dict, list)):
            text = json.dumps(obj, ensure_ascii=False, default=str)
        else:
            text = str(obj)
        return text if len(text) <= max_len else text[:max_len] + "..."
    except Exception:
        return "[无法预览]"


def _messages_to_frontend_format(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """LangChain 消息历史 → 前端 ChatMessage[] 结构。

    原始历史里一次问答 = user + ai(tool_calls) + tool*N + ai(正文)，
    前端实时聊天渲染时是把工具调用都挂在一条 assistant 消息的 tool_runs 上，
    所以这里同样做聚合，恢复出来的界面才和实时聊天一致。
    """
    items: List[Dict[str, Any]] = []
    current_ai: Optional[Dict[str, Any]] = None  # 当前正在聚合的 assistant 消息

    for m in messages:
        if not isinstance(m, BaseMessage):
            continue

        if isinstance(m, HumanMessage):
            items.append({"role": "user", "content": m.content or ""})
            current_ai = None
            continue

        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            # 带工具调用的 AI 消息：开（或复用）一条 assistant，把调用挂到 tool_runs
            if current_ai is None:
                current_ai = {"role": "assistant", "content": "", "tool_runs": []}
                items.append(current_ai)
            for tc in m.tool_calls:
                current_ai.setdefault("tool_runs", []).append({
                    "name": tc.get("name", ""),
                    "input": tc.get("args") or {},
                    "output": None,
                    "status": "running",
                    # 内部字段：给下一条 ToolMessage 配对用，前端用不到但无害
                    "_call_id": tc.get("id", ""),
                })
            continue

        if isinstance(m, ToolMessage):
            # 工具结果：按 tool_call_id 回填到最近一条 running 的同名调用
            call_id = getattr(m, "tool_call_id", "")
            output = _parse_json_if_possible(m.content)
            if current_ai is not None:
                for run in reversed(current_ai.get("tool_runs", [])):
                    if run.get("_call_id") == call_id and run["status"] == "running":
                        run["output"] = output
                        run["status"] = "ok"
                        break
            continue

        if isinstance(m, AIMessage):
            # 纯正文回答：填进正在聚合的 assistant；没有就新开一条
            content = m.content if isinstance(m.content, (str, list)) else str(m.content)
            if not content:
                continue
            if current_ai is not None:
                current_ai["content"] = content
                current_ai = None
            else:
                items.append({"role": "assistant", "content": content})
            continue
        # SystemMessage 等不参与前端渲染，跳过
    return items


def _message_to_persist(m: BaseMessage) -> Dict[str, Any]:
    """LangChain Message → 可 JSON 序列化的持久化结构（存 MySQL）"""
    item: Dict[str, Any] = {
        "t": _msg_role(m),
        "content": m.content if isinstance(m.content, (str, list)) else str(m.content),
    }
    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        # 保留 id：恢复后要和 ToolMessage.tool_call_id 配对，LLM 才认得这是完整的工具调用链
        item["tool_calls"] = [
            {
                "name": tc.get("name"),
                "args": tc.get("args") or {},
                "id": tc.get("id"),
                "type": tc.get("type", "tool_call"),
            }
            for tc in m.tool_calls
        ]
    if isinstance(m, ToolMessage):
        item["name"] = getattr(m, "name", "")
        item["tool_call_id"] = getattr(m, "tool_call_id", "")
    return item


def _persist_to_message(item: Dict[str, Any]) -> Optional[BaseMessage]:
    """持久化结构 → LangChain Message（从 MySQL 恢复时用）"""
    role = item.get("t")
    content = item.get("content", "")
    if role == "user":
        return HumanMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content, tool_calls=item.get("tool_calls") or [])
    if role == "tool":
        return ToolMessage(
            content=content,
            name=item.get("name", ""),
            tool_call_id=item.get("tool_call_id", ""),
        )
    if role == "system":
        return SystemMessage(content=content)
    return None