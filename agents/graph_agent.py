# -*- coding: utf-8 -*-
"""
GraphAgent：LangGraph 状态机定义（agent → inject_session → tools → agent …）
只管图结构和节点逻辑；对外由 services/graph_service.py 驱动。

演示：python -m agents.graph_agent
"""
import os
import asyncio
import logging
import aiomysql
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

from agents.llm_client import create_llm
from tools.langchain_tool import ALL_TOOLS
from agents.AgentState import AgentState

from config.model_config import SYSTEM_PROMPT
from config.mysql_config import DATABASE_CONFIG

CHECKPOINT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "checkpoints.db")

LLM = create_llm()

_llm_logger = logging.getLogger("llm_io")
_llm_logger.setLevel(logging.INFO)
if not _llm_logger.handlers:
    os.makedirs("data", exist_ok=True)
    _fh = logging.FileHandler("data/llm_io.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _llm_logger.addHandler(_fh)
    _llm_logger.propagate = False


class GraphAgent:

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
        messages_with_sys = [("system", SYSTEM_PROMPT)] + state["messages"]
        sid = state.get("session_id", "default")
        _llm_logger.info("[INPUT ] session=%s | %s", sid, messages_with_sys)
        response = self.llm_with_tools.invoke(messages_with_sys)
        _llm_logger.info("[OUTPUT] session=%s | %s", sid, response)
        return {"messages": [response]}

    def inject_session_node(self, state: AgentState, config: RunnableConfig):
        sid = config.get("configurable", {}).get("thread_id", "default")
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                if "args" not in tc:
                    tc["args"] = {}
                tc["args"]["session_id"] = sid
        return {"messages": state["messages"]}

    def should_continue(self, state: AgentState):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "inject_session"
        return "skill_check"

    @staticmethod
    def route_after_skill(state: "AgentState"):
        route = state.get("skill_route")
        return END if route == "end" else route

if __name__ == "__main__":
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