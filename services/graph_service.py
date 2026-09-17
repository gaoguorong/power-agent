import json
import math
import asyncio
import traceback
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from langgraph.errors import GraphRecursionError

from agents.graph_agent import GraphAgent
from executors.base import ToolExecutionRequest
from executors.registry import build_default_registry
from schemas.tool_result import normalize_tool_result
from tools import langchain_tool
from tools.langchain_tool import ALL_TOOLS
from skills.skill_runner import (match_skill, match_skill_after_llm,
                                   run_overload_relief, run_load_sweep)

from .graph_util import (_safe_preview, _sanitize_non_finite, _parse_json_if_possible,
                         _fill_tool_run,_messages_to_frontend_format)

RECURSION_LIMIT = 45
_SKILL_DONE = object()


class GraphService:

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
        self._compiled = None
        self._checkpointer = None
        self._tools_by_name = {t.name: t for t in ALL_TOOLS}
        self._registry = build_default_registry()
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def ensure_init(self):
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self._graph_agent.async_init()
            self._compiled = self._graph_agent._compiled
            self._checkpointer = self._graph_agent.checkpointer
            self._initialized = True
            print("[GraphService] Checkpointer(AsyncSqliteSaver) 已就绪")

    async def _tools_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        last_msg = state["messages"][-1]
        if not (isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None)):
            return {}
        return {"messages": await asyncio.to_thread(self._execute_tools, last_msg.tool_calls)}

    def _skill_check_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        gt = langchain_tool.get_gt_obj(state.get("session_id", "default"))
        skill = match_skill_after_llm(state.get("question", ""), gt)
        return {"matched_skill": skill}

    # ==============================================================
    # 0.5 Checkpointer 辅助：图跑完自动存，skill 旁路要手动写一次
    # ==============================================================
    async def _checkpoint_get_messages(self, session_id: str) -> List[BaseMessage]:
        config = {"configurable": {"thread_id": session_id}}
        tuple_ = await self._checkpointer.aget_tuple(config)
        if tuple_ is None or not tuple_.checkpoint:
            return []
        msgs = tuple_.checkpoint.get("messages", [])
        return [m for m in msgs if isinstance(m, BaseMessage)]

    async def _checkpoint_put(self, session_id: str, state: Dict[str, Any], source: str = "skill") -> None:
        """手动往 checkpointer 写一次 state（skill 旁路跑完后用）"""
        try:
            config = {"configurable": {"thread_id": session_id}}
            tuple_ = await self._checkpointer.aget_tuple(config)
            existing = tuple_.checkpoint if tuple_ else {}
            checkpoint = {**existing, "messages": state["messages"]}
            step = ((tuple_.metadata or {}).get("step", 0) + 1) if tuple_ else 0
            await self._checkpointer.aput(config, checkpoint, {"source": source, "step": step})
        except Exception:
            pass

    # ==============================================================
    # 1. 流式聊天：驱动编译图逐节点产出，转成 SSE 事件
    # ==============================================================

    async def chat_stream(
        self,
        session_id: str,
        question: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        await self.ensure_init()

        cfg = {"configurable": {"thread_id": session_id},
               "recursion_limit": RECURSION_LIMIT}

        state: Dict[str, Any] = {
            "messages": [HumanMessage(content=question)],
            "session_id": session_id,
            "question": question,
        }

        msgs: List[BaseMessage] = []
        tool_runs: List[Dict[str, Any]] = []

        yield {"event": "welcome", "data": {"session_id": session_id, "question": question}}

        try:
            skill_done = False
            async for ev in self._run_skill_channel(session_id, question, state, tool_runs):
                if ev is _SKILL_DONE:
                    skill_done = True
                    continue
                yield ev
            if skill_done:
                return

            async for chunk in self._compiled.astream(state, config=cfg, stream_mode="updates"):
                for node_name, update in chunk.items():
                    if node_name == "agent":
                        ai_msg = update["messages"][-1]
                        msgs.append(ai_msg)

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
                            if text:
                                yield {"event": "token", "data": {"text": text}}
                            yield {"event": "done",
                                   "data": {"ai_text": text, "tool_runs": tool_runs}}
                            return

                        for tc in ai_msg.tool_calls:
                            args = tc.get("args") or {}
                            tool_runs.append({"name": tc["name"], "input": args,
                                              "output": None, "status": "running",
                                              "_call_id": tc.get("id", "")})
                            yield {"event": "tool_start", "data": {
                                "name": tc["name"],
                                "input": _safe_preview(args),
                                "run_id": tc.get("id", ""),
                            }}

                    elif node_name == "tools":
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
                        matched = update.get("matched_skill")
                        if matched is not None:
                            async for ev in self._run_skill_channel(
                                    session_id, question, {"messages": msgs}, tool_runs,
                                    pre_matched_skill=matched):
                                if ev is _SKILL_DONE:
                                    return
                                yield ev
                            return
            yield {"event": "done", "data": {"ai_text": "", "tool_runs": tool_runs,
                                             "warning": "max_rounds"}}

        except GraphRecursionError:
            yield {"event": "done", "data": {"ai_text": "", "tool_runs": tool_runs,
                                             "warning": "max_rounds"}}
        except Exception as exc:
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
        skill = pre_matched_skill if pre_matched_skill is not None else match_skill(question)
        if skill is None:
            return
        gt = langchain_tool.get_gt_obj(session_id)
        if pre_matched_skill is None and getattr(gt, "net", None) is None:
            return

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
                tool_runs.append({"name": name, "input": inp, "output": None,
                                  "status": "running", "_call_id": call_id})
                yield {"event": "tool_start", "data": {
                    "name": name, "input": _safe_preview(inp), "run_id": call_id}}
                _fill_tool_run(tool_runs, name, out, call_id)
                yield {"event": "tool_end", "data": {
                    "name": name, "output_preview": _safe_preview(out, 200)}}
                tool_calls.append({"name": name, "args": inp, "id": call_id, "type": "tool_call"})
                tool_msgs.append(ToolMessage(
                    content=json.dumps(out, ensure_ascii=False, default=str),
                    name=name, tool_call_id=call_id))

            elif kind == "final":
                if ev.get("aborted"):
                    return
                final_text = ev.get("text", "") or ""

        if tool_calls:
            state["messages"].append(AIMessage(content="", tool_calls=tool_calls))
            state["messages"].extend(tool_msgs)
        if final_text:
            state["messages"].append(AIMessage(content=final_text))
        await self._checkpoint_put(session_id, state, source="skill")

        if final_text:
            yield {"event": "token", "data": {"text": final_text}}
        yield {"event": "done", "data": {"ai_text": final_text, "tool_runs": tool_runs}}
        yield _SKILL_DONE

    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolMessage]:
        results: List[ToolMessage] = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}

            entry = self._registry.get(name)
            if entry is not None:
                definition, _adapter = entry
                normalized = self._registry.execute(ToolExecutionRequest(
                    tool_id=name,
                    parameters=args,
                    timeout_seconds=definition.timeout_seconds,
                ))
            else:
                tool = self._tools_by_name.get(name)
                if tool is None:
                    normalized = normalize_tool_result(
                        RuntimeError(f"未知工具 '{name}'"), name)
                else:
                    try:
                        raw = tool.invoke(args)
                    except Exception as exc:
                        raw = exc
                    normalized = normalize_tool_result(raw, name)

            normalized = _sanitize_non_finite(normalized)
            text = json.dumps(normalized, ensure_ascii=False, indent=2, default=str)
            results.append(ToolMessage(content=text, name=name, tool_call_id=tc.get("id", "")))
        return results

    # ==============================================================
    # 2. 消息历史查询：从 LangGraph Checkpointer 读取
    # ==============================================================

    async def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        await self.ensure_init()
        msgs = await self._checkpoint_get_messages(session_id)
        return _messages_to_frontend_format(msgs)

    # ==============================================================
    # 3. 电网对象状态管理
    # ==============================================================

    @staticmethod
    def _grid_sessions() -> Dict[str, Any]:
        return getattr(langchain_tool, "_sessions", {})

    def has_grid_session(self, session_id: str) -> bool:
        return session_id in self._grid_sessions()

    def reset_grid_session(self, session_id: str) -> None:
        self._grid_sessions().pop(session_id, None)

    def get_session_grid_meta(self, session_id: str) -> Dict[str, Any]:
        gt = self._grid_sessions().get(session_id)
        if gt is None:
            return {}
        meta: Dict[str, Any] = {}

        grid_type = getattr(gt, "_patched_grid_type", None)
        if grid_type:
            meta["last_grid_type"] = grid_type

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

