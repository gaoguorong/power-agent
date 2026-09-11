# -*- coding: utf-8 -*-
"""
GraphAgent：LangGraph 状态机定义（agent → inject_session → tools → agent …）
只管图结构和节点逻辑；对外由 services/graph_service.py 驱动。

演示：python -m agents.graph_agent
"""
import os
import logging
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agents.llm_client import create_llm
from tools.langchain_tool import ALL_TOOLS
from agents.AgentState import AgentState, ServiceState

from config.model_config import SYSTEM_PROMPT

# 全进程共用的 LLM 实例（模块加载时创建一次）
LLM = create_llm()

# LLM 交互留痕：用最简 logging 把每轮发给大模型的输入/输出追加到 data/llm_io.log
# （data/ 已在 .gitignore 忽略）。注意：光 logger.info 不落盘，必须挂一个 FileHandler。
_llm_logger = logging.getLogger("llm_io")
_llm_logger.setLevel(logging.INFO)
if not _llm_logger.handlers:                 # 防止 --reload 重复挂 handler
    os.makedirs("data", exist_ok=True)
    _fh = logging.FileHandler("data/llm_io.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _llm_logger.addHandler(_fh)
    _llm_logger.propagate = False


class GraphAgent:

    def __init__(self,tools_node, skill_check_node):

        self.llm_with_tools = LLM.bind_tools(ALL_TOOLS, tool_choice="auto", strict=True)
        self.memory_saver = MemorySaver()
        self.tool_node = ToolNode(ALL_TOOLS)

        graph = StateGraph(AgentState)
        graph.add_node("agent", self.agent_node)
        graph.add_node("inject_session", self.inject_session_node)
        graph.add_node("tools", tools_node)
        graph.add_node("skill_check", skill_check_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self.should_continue, {
            "inject_session": "inject_session",
            END: END,
        })
        graph.add_edge("inject_session", "tools")
        graph.add_edge("tools", "skill_check")
        graph.add_conditional_edges("skill_check", self.route_after_skill, {
            "agent": "agent",
            END: END,
        })
        self._compiled = graph.compile()

    # ============================================================
    # 2. Agent 节点：LLM 决定下一步（回答 or 调工具）
    # ============================================================
    def agent_node(self,state: AgentState):
        messages_with_sys = [("system", SYSTEM_PROMPT)] + state["messages"]
        sid = state.get("session_id", "default")
        _llm_logger.info("[INPUT ] session=%s | %s", sid, messages_with_sys)
        response = self.llm_with_tools.invoke(messages_with_sys)
        _llm_logger.info("[OUTPUT] session=%s | %s", sid, response)
        return {"messages": [response]}

    # ============================================================
    # 3. inject_session 节点：从 config 的 thread_id 注入到每个 tool_call 的 args
    #    thread_id 即会话唯一键，同时驱动 Checkpointer(消息历史) 和 _sessions(电网对象)，
    #    两者一一对应，彻底避免调用方传两次 session_id 导致的不一致。
    # ============================================================
    def inject_session_node(self,state: AgentState, config: RunnableConfig):
        sid = config.get("configurable", {}).get("thread_id", "default")
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                if "args" not in tc:
                    tc["args"] = {}
                tc["args"]["session_id"] = sid
        return {"messages": state["messages"]}

    # ============================================================
    # 4. 条件边：决定下一步是继续调工具，还是直接结束
    # ============================================================

    def should_continue(self,state: AgentState):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "inject_session"
        return END

    # ============================================================
    # 5. 服务侧编译图：基础 agent 循环 + 服务注入的 tools/skill_check 节点。
    #    不挂 checkpointer：历史由 GraphService 自管，每次调用全量传入，
    #    避免 skill 半路接管后 checkpoint 残留半截消息。
    # ============================================================
    @staticmethod
    def route_after_skill(state: "ServiceState"):
        """skill_check 之后的路由：命中技能直接结束（服务层接管跑确定性闭环），
        未命中回到 agent 继续下一轮。"""
        return END if state.get("matched_skill") else "agent"

    def _print_result(self,title: str, result: dict):
        print(f"\n{'=' * 60}\n> {title}\n{'=' * 60}")
        last_msg = result["messages"][-1]
        print("[最终回答]:\n", last_msg.content)
        print(f"\n[对话统计] 本次消息数: {len(result['messages'])}")
        for i, m in enumerate(result["messages"]):
            tag = type(m).__name__
            if isinstance(m, ToolMessage):
                content_preview = m.content[:200].replace("\n", " ")
                print(f"  [{i}] {tag} status={m.status} name={m.name} preview='{content_preview}...'")
            elif isinstance(m, AIMessage) and m.tool_calls:
                print(f"  [{i}] {tag} tool_calls={[(tc['name'], list(tc['args'].keys())) for tc in m.tool_calls]}")
            else:
                txt = (m.content or "").replace("\n", " ")[:150]
                print(f"  [{i}] {tag} content='{txt}...'")


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # 演示：两个独立会话并行（张三 case30 研究  vs  李四 case57 潮流+N-1）
    # 切换会话 = 换一个带新 thread_id 的 config 即可，两者完全隔离。
    # ------------------------------------------------------------------
    cfg_zhangsan = {"configurable": {"thread_id": "sess-zhangsan-demo-001"}}
    cfg_lisi     = {"configurable": {"thread_id": "sess-lisi-demo-001"}}

    graph_agent = GraphAgent()
    graph = graph_agent.graph
    agent = graph.compile(checkpointer=graph_agent.memory_saver)

    zs_r1 = agent.invoke(
        {"messages": [HumanMessage("基于30节点电网模型进行潮流计算/30节点潮流计算，分析是否出现线路过载?分析是否出现电压越限?")]},
        config=cfg_zhangsan
    )
    graph_agent._print_result("张三 第1轮: case30建网+潮流+过载分析", zs_r1)


    # ls_r1 = agent.invoke(
    #     {"messages": [HumanMessage("你好，请用 57 节点电网进行潮流计算，然后进行 N-1 安全校核分析，给我结果。")]},
    #     config=cfg_lisi
    # )
    # _print_result("李四 第1轮: case57潮流+N-1校核（新会话，独立case57电网）", ls_r1)
    #
    #
    # zs_r3 = agent.invoke(
    #     {"messages": [HumanMessage("之前我的 case30 是 1.8 倍负荷，现在再做一个 N-1 校核，只看前 10 条线路。")]},
    #     config=cfg_zhangsan
    # )
    # _print_result("张三 第3轮: N-1校核前10条线（自动找回之前1.8倍负荷的case30）", zs_r3)
