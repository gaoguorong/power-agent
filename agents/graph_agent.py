# -*- coding: utf-8 -*-
"""
GraphAgent：LangGraph 状态机定义（agent → inject_session → tools → agent …）
只管图结构和节点逻辑；对外由 services/graph_service.py 驱动。

演示：python -m agents.graph_agent
"""
import asyncio
import logging
import aiomysql
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

from agents.llm_client import create_llm
from tools.langchain_tool import ALL_TOOLS
from agents.AgentState import AgentState

from config.model_config import SYSTEM_PROMPT
from config.mysql_config import DATABASE_CONFIG
from langgraph.types import interrupt,Command

from config.log_config import setup_logging

LLM = create_llm()


def _interrupt(value, config: RunnableConfig):
    """interrupt() 的 py3.10 兼容包装。
    langgraph 在 Python < 3.11 下走 astream 异步执行时不会传播 runnable config
    """
    token = var_child_runnable_config.set(config)
    try:
        return interrupt(value)
    finally:
        var_child_runnable_config.reset(token)

# 【修改 2026-10-22】日志配置已集中到 config/log_config.py（main.py 启动时装配），
# 这里只按名称取记录器，不感知日志文件路径与滚动策略；内容截断240字。
_llm_logger = logging.getLogger("llm_io")


def _sanitize_tool_call_history(messages):
    """清理消息历史中不合规的 tool_calls。

    LLM API 要求：每条带 tool_calls 的 AIMessage 后面必须紧跟对应
    tool_call_id 的 ToolMessage。如果历史里存在：
      1) 有 tool_calls 但缺 ToolMessage 的 AIMessage；
      2) ToolMessage 存在但没有紧跟在对应 AIMessage 后面；
    都会触发 'insufficient tool messages following tool_calls message' 400 错误。

    本函数扫描历史，对每条带 tool_calls 的 AIMessage：
      - 检查其紧随其后的消息是否是 ToolMessage；
      - 收集所有 ToolMessage 的 tool_call_id；
      - 只保留那些 id 存在且紧随其后有对应 ToolMessage 的 tool_call。
    其余 tool_call 全部剔除，保证历史可被 LLM API 接受。
    """
    seen_tool_call_ids = set()
    for m in messages:
        if isinstance(m, ToolMessage):
            cid = getattr(m, "tool_call_id", None)
            if cid:
                seen_tool_call_ids.add(cid)

    changed = False
    for idx, m in enumerate(messages):
        if not isinstance(m, AIMessage):
            continue
        tcs = getattr(m, "tool_calls", None) or []
        if not tcs:
            continue

        next_msg = messages[idx + 1] if idx + 1 < len(messages) else None
        next_is_tool = isinstance(next_msg, ToolMessage)

        if not next_is_tool:
            m.tool_calls = []
            changed = True
            continue

        valid = [
            tc for tc in tcs
            if tc.get("id") in seen_tool_call_ids
            and getattr(next_msg, "tool_call_id", None) == tc.get("id")
        ]
        if len(valid) != len(tcs):
            m.tool_calls = valid
            changed = True
    return changed


class GraphAgent:

    @staticmethod
    def _preview(value: str) -> str:
        compact = " ".join(value.split())
        return compact[:240] + ("..." if len(compact) > 240 else "")

    # 【新增 2026-10-22】作用：把LangChain消息类型翻译成中文标签（用户/模型/工具结果），提高日志可读性
    @staticmethod
    def _role_label(message) -> str:
        labels = {"HumanMessage": "用户", "AIMessage": "模型", "ToolMessage": "工具结果"}
        return labels.get(type(message).__name__, type(message).__name__) if message else "无"

    # 【新增 2026-10-22】作用：把模型的工具调用压成一行可读文本（最多显示3个调用，总长240字截断）
    @staticmethod
    def _format_tool_calls(tool_calls) -> str:
        parts = []
        for item in (tool_calls or [])[:3]:
            args = ", ".join(f"{key}={value}" for key, value in (item.get("args") or {}).items())
            parts.append(f"{item.get('name', 'unknown')}({args})")
        text = ", ".join(parts) or "无"
        return text[:240] + ("..." if len(text) > 240 else "")

    @staticmethod
    def route_after_skill(state: "AgentState"):
        route = state.get("skill_route")
        return END if route == "end" else route

    def __init__(self, tools_node, skill_check_node):
        self.llm_with_tools = LLM.bind_tools(ALL_TOOLS, tool_choice="auto", strict=True)
        self.tool_node = ToolNode(ALL_TOOLS)
        self.checkpointer = None
        self._compiled = None
        self._mysql_conn = None

        graph = StateGraph(AgentState)
        graph.add_node("agent", self.agent_node)
        graph.add_node("inject_session", self.inject_session_node)
        graph.add_node("tools", tools_node)
        graph.add_node("skill_check", skill_check_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self.should_continue, {
            "inject_session": "inject_session",
            "skill_check": "skill_check",
        })
        graph.add_edge("inject_session", "tools")
        graph.add_edge("tools", "skill_check")
        graph.add_conditional_edges("skill_check", self.route_after_skill, {
            "agent": "agent",
            END: END,
        })
        self._graph = graph

    async def async_init(self):
        conn_kwargs = AIOMySQLSaver.parse_conn_string(DATABASE_CONFIG["mysql_url"])
        self._mysql_conn = await aiomysql.connect(**conn_kwargs, autocommit=True)
        self.checkpointer = AIOMySQLSaver(conn=self._mysql_conn)
        await self.checkpointer.setup()
        self._compiled = self._graph.compile(checkpointer=self.checkpointer)

    async def close(self):
        if self._mysql_conn is not None:
            try:
                self._mysql_conn.close()
                await self._mysql_conn.wait_closed()
            except Exception:
                pass
            self._mysql_conn = None

    def agent_node(self, state: AgentState):
        messages = list(state["messages"])
        if _sanitize_tool_call_history(messages):
            _llm_logger.warning("[历史修复] session=%s 检测到孤立 tool_calls 并已清理",
                                state.get("session_id", "default"))
        messages_with_sys = [("system", SYSTEM_PROMPT)] + messages
        sid = state.get("session_id", "default")
        latest_message = state["messages"][-1] if state["messages"] else None
        latest_text = str(getattr(latest_message, "content", ""))
        # 【修改 2026-10-22】调用前日志：单行记 会话ID/消息数/消息来源(用户/模型/工具结果)/内容预览
        _llm_logger.info(
            "[输入] session=%s | 消息数=%d | %s: %s",
            sid, len(state["messages"]), self._role_label(latest_message),
            self._preview(latest_text),
        )
        response = self.llm_with_tools.invoke(messages_with_sys)
        response_text = str(getattr(response, "content", ""))
        # 【修改 2026-10-22】调用后日志：单行记 会话ID/模型决定调用的工具及参数/回复预览
        _llm_logger.info(
            "[输出] session=%s | 调用工具: %s | 回复: %s",
            sid, self._format_tool_calls(getattr(response, "tool_calls", None)),
            self._preview(response_text),
        )
        return {"messages": [response]}

    def inject_session_node(self, state: AgentState, config: RunnableConfig):
        sid = config.get("configurable", {}).get("thread_id", "default")
        last_msg = state["messages"][-1]
        # 挂起态被插入新输入时最后一条可能不是 AIMessage（没有 tool_calls 属性），
        # 统一用 getattr 取，避免 AttributeError
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        for tc in tool_calls:
            if "args" not in tc:
                tc["args"] = {}
            tc["args"]["session_id"] = sid
        risky_tools = {"adjust_gen_output","disconnect_line",
                       "connect_line","load_case","set_load_mw","set_load_scale"}
        has_risky = any(tc["name"] in risky_tools for tc in tool_calls)
        if has_risky:
            decision = _interrupt({
                "question": "计划执行一下操作，是否继续?",
                "tool_calls":[
                    {"name": tc["name"], "args": tc["args"]}
                    for tc in last_msg.tool_calls
                ],
            }, config)
            if decision != "approve":
                # 拒绝：把 tool_calls 清掉，回 agent 让 AI 换个方案
                last_msg.tool_calls = []
                last_msg.content = "用户拒绝了该操作，请重新考虑方案。"
        # 只返回被修改的 last_msg，让 add_messages 按 id 原地更新，
        # 避免回传整份 state["messages"] 触发重复追加或顺序错乱。
        return {"messages": [last_msg]}

    def should_continue(self, state: AgentState):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "inject_session"
        return "skill_check"



if __name__ == "__main__":

    setup_logging()  # 独立运行演示时自行装配日志
    cfg_zhangsan = {"configurable": {"thread_id": "sess-zhangsan-demo-001"}}
    cfg_lisi     = {"configurable": {"thread_id": "sess-lisi-demo-001"}}

    async def demo():
        graph_agent = GraphAgent()
        await graph_agent.async_init()
        agent = graph_agent._compiled

        zs_r1 = await agent.ainvoke(
            {"messages": [HumanMessage("基于30节点电网模型进行潮流计算/30节点潮流计算，分析是否出现线路过载?分析是否出现电压越限?")]},
            config=cfg_zhangsan
        )
        graph_agent._print_result("张三 第1轮: case30建网+潮流+过载分析", zs_r1)

    asyncio.run(demo())