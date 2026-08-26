import os
import sys, io, warnings, logging
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from llm_client import LLMClient
from tools.langchain_tool import ALL_TOOLS, query_knowledge

from config.SYSTEM_PROMPT import SYSTEM_PROMPT

os.environ["PYTHONUTF8"]         = "1"
os.environ["PYTHONIOENCODING"]   = "utf-8:replace"
os.environ["NO_COLOR"]           = "1"
os.environ["ANSI_COLORS_DISABLED"] = "1"
os.environ["TQDM_DISABLE"]       = "1"
os.environ["LANG"]               = "zh_CN.UTF-8"

warnings.filterwarnings("ignore")
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("langgraph").setLevel(logging.WARNING)
logging.getLogger("pandapower").setLevel(logging.WARNING)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)


llm_client = LLMClient()
llm = llm_client.llm

class GraphAgent:

    def __init__(self):

        self.llm_with_tools = llm.bind_tools(ALL_TOOLS, tool_choice="auto", strict=True)
        self.memory_saver = MemorySaver()
        self.tool_node = ToolNode(ALL_TOOLS)

        self.graph = StateGraph(self.AgentState)
        self.graph.add_node("agent", self.agent_node)
        self.graph.add_node("inject_session", self.inject_session_node)
        self.graph.add_node("tools", self.tool_node)

        self.graph.add_edge(START, "agent")
        self.graph.add_conditional_edges("agent", self.should_continue, {
            "inject_session": "inject_session",
            END: END,
        })
        self.graph.add_edge("inject_session", "tools")
        self.graph.add_edge("tools", "agent")

    # ============================================================
    # 1. State 定义：messages(对话历史) + session_id(上下文路由键)
    # ============================================================
    class AgentState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        session_id: str

    # ============================================================
    # 2. Agent 节点：LLM 决定下一步（回答 or 调工具）
    # ============================================================
    def agent_node(self,state: AgentState):
        messages_with_sys = [("system", SYSTEM_PROMPT)] + state["messages"]
        response = self.llm_with_tools.invoke(messages_with_sys)
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
    agent = graph_agent.graph.compile(checkpointer=graph_agent.memory_saver)

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