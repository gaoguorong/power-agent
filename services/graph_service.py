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
import traceback
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage

from GraphAgent import GraphAgent
from tools import langchain_tool
from tools.langchain_tool import ALL_TOOLS

# 单次聊天内最多允许多少轮「LLM思考 → 调工具」，防止异常情况下死循环
MAX_TOOL_ROUNDS = 10


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
        # 工具按名字索引，执行 tool_calls 时用
        self._tools_by_name = {t.name: t for t in ALL_TOOLS}
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
        ga = self._graph_agent
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
            for _ in range(MAX_TOOL_ROUNDS):
                # 1) LLM 决策：要么直接回答，要么给出要调用的工具清单
                ai_msg = await asyncio.to_thread(ga.agent_node, state)
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
                                      "output": None, "status": "running"})
                    yield {"event": "tool_start", "data": {
                        "name": tc["name"],
                        "input": _safe_preview(args),
                        "run_id": tc.get("id", ""),
                    }}

                # 4) 把 session_id 注入每个工具的 args（多会话电网隔离靠它）
                await asyncio.to_thread(ga.inject_session_node, state, cfg)

                # 5) 真正执行工具，结果回填给状态机 + 播报给前端
                tool_msgs = await asyncio.to_thread(self._execute_tools, ai_msg.tool_calls)
                state["messages"].extend(tool_msgs)
                for tm in tool_msgs:
                    output = _parse_json_if_possible(tm.content)
                    _fill_tool_run(tool_runs, tm.name, output)
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

    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolMessage]:
        """按名字找到工具逐个执行，结果统一包成 ToolMessage"""
        results: List[ToolMessage] = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}
            tool = self._tools_by_name.get(name)
            if tool is None:
                text = f"错误：未知工具 '{name}'"
            else:
                try:
                    raw = tool.invoke(args)
                    if isinstance(raw, (dict, list)):
                        text = json.dumps(raw, ensure_ascii=False, indent=2)
                    else:
                        text = str(raw)
                except Exception as exc:
                    text = f"工具执行异常: {type(exc).__name__}: {exc}"
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
        """返回该会话的完整消息历史（前端可读格式）"""
        return [_message_to_dict(m)
                for m in self._session_messages.get(session_id, [])
                if isinstance(m, BaseMessage)]

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

def _message_to_dict(m: BaseMessage) -> Dict[str, Any]:
    """把 LangChain Message 转成前端可读的 dict"""
    item: Dict[str, Any] = {
        "role": _msg_role(m),
        "content": m.content if isinstance(m.content, (str, list)) else str(m.content),
    }
    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        item["tool_calls"] = m.tool_calls
    if isinstance(m, ToolMessage):
        item["tool_name"] = getattr(m, "name", "")
        item["tool_call_id"] = getattr(m, "tool_call_id", "")
    return item


def _msg_role(m: BaseMessage) -> str:
    """LangChain Message 类型 → 前端认识的 role 字符串"""
    if isinstance(m, HumanMessage):
        return "user"
    if isinstance(m, AIMessage):
        return "assistant"
    if isinstance(m, ToolMessage):
        return "tool"
    return type(m).__name__.lower()


def _fill_tool_run(tool_runs: List[Dict[str, Any]], name: str, output: Any) -> None:
    """把执行结果回填到 tool_runs 里最近一条同名 running 记录"""
    for run in reversed(tool_runs):
        if run["name"] == name and run["status"] == "running":
            run["output"] = _safe_preview(output)
            run["status"] = "ok"
            return


def _parse_json_if_possible(text: Any) -> Any:
    """工具输出是 JSON 字符串就解析成 dict（前端展示更好看），否则原样返回"""
    if isinstance(text, str):
        try:
            return json.loads(text)
        except Exception:
            return text
    return text


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
