import os
# ---------- PyCharm 调试器编码兜底（必须在任何第三方 import 之前设置） ----------
os.environ["PYTHONUTF8"]         = "1"
os.environ["PYTHONIOENCODING"]   = "utf-8:replace"
os.environ["NO_COLOR"]           = "1"
os.environ["ANSI_COLORS_DISABLED"] = "1"
os.environ["TQDM_DISABLE"]       = "1"
os.environ["LANG"]               = "zh_CN.UTF-8"

import sys, io, warnings, logging
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
# -----------------------------------------------------------------------------

from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from llm_client import create_llm
from tools.langchain_tool import ALL_TOOLS, query_knowledge



llm = create_llm()

llm_with_tools = llm.bind_tools(ALL_TOOLS)

# ============================================================
# 1. State 定义：messages(对话历史) + session_id(上下文路由键)
# ============================================================
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str

# ============================================================
# 2. Agent 节点：LLM 决定下一步（回答 or 调工具）
# ============================================================
SYSTEM_PROMPT = (
    "你是一名专业的电网静态安全分析助手，使用提供的工具回答用户问题。\n"
    "【模式建议】\n"
    "· 用户要整体分析（如：分析XX节点电网、给我一份风险报告）→ 优先调 run_full_analysis 复合工具，一次搞定。\n"
    "· 用户要分步操作（如：先建电网，再调负荷2倍，再看过载）→ 用对应的原子工具逐步调用。\n"
    "· 用户问定义/规程/依据（如：什么是N-1准则）→ 调 query_knowledge，不要调任何计算工具。\n"
    "【歧义澄清规则（重要！关乎计算正确性）】\n"
    "· 如果用户提出了新的计算类任务，且同时满足以下两条：\n"
    "    1) 问题中没有明确出现'刚才/之前/这个/当前/继续'等指代当前上下文的词；\n"
    "    2) 问题中也没有明确指定电网类型（如 case9/case14/case30/case39/case57/case118/case300/xx节点）。\n"
    "· 那么请不要直接调任何计算工具，先反问用户澄清，格式参考：\n"
    "  请问您是想基于刚才已创建的电网继续分析，还是想使用一个全新的电网模型？\n"
    "  如果是新模型请指定节点类型（如 case30/30节点/case57/57节点/case118/118节点 等）。\n"
    "【会话显式重置规则】\n"
    "· 当用户明确表达了'清空重来'、'重新开始'、'不要之前的电网了'、'恢复初始状态'、\n"
    "  '放弃之前的计算'这类意图时，先调用 reset_grid_session 工具清空电网状态，\n"
    "  再根据后续需求执行。注意：reset_grid_session 只清计算状态，不会清聊天记录。\n"
    "【注意事项】\n"
    "· 任何计算类工具之前，必须先调用 create_test_grid（或 run_full_analysis 内部已包含），否则会报错。\n"
    "· 如果用户说的是'刚才/之前/继续'这类指代词，说明是多轮对话的延续，请基于之前的工具结果继续。\n"
    "· 如果用户新问题里明确指定了新的电网类型（例如之前聊 case30，现在说'用57节点'），\n"
    "  直接调用 create_test_grid(新类型) 覆盖当前会话的电网即可，不需要向用户确认是否重置。\n"
    "· 工具返回 success=False 时，请把错误信息清晰告知用户，不要瞎编结果。\n"
    "· 输出最终回答时，请用简洁的中文总结关键数据，不要把工具返回的大段 JSON 原样复制。"
)

def agent_node(state: AgentState):
    messages_with_sys = [("system", SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages_with_sys)
    return {"messages": [response]}

# ============================================================
# 3. inject_session 节点：从 config 的 thread_id 注入到每个 tool_call 的 args
#    thread_id 即会话唯一键，同时驱动 Checkpointer(消息历史) 和 _sessions(电网对象)，
#    两者一一对应，彻底避免调用方传两次 session_id 导致的不一致。
# ============================================================
def inject_session_node(state: AgentState, config: RunnableConfig):
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
def should_continue(state: AgentState):
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "inject_session"
    return END


# ============================================================
# 5. 组装 LangGraph StateGraph
# ============================================================

memory_saver = MemorySaver()
tool_node = ToolNode(ALL_TOOLS)

graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("inject_session", inject_session_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue, {
    "inject_session": "inject_session",
    END: END,
})
graph.add_edge("inject_session", "tools")
graph.add_edge("tools", "agent")

agent = graph.compile(checkpointer=memory_saver)


# ============================================================
# 6. 测试：3 个典型场景（可按需注释/打开）
# ============================================================
def _print_result(title: str, result: dict):
    print(f"\n{'='*60}\n> {title}\n{'='*60}")
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

    # === 张三会话：case30 分步研究（3 轮）===

    zs_r1 = agent.invoke(
        {"messages": [HumanMessage("帮我建一个 case30 测试电网，然后算交流潮流，给我看看有没有过载的线路。")]},
        config=cfg_zhangsan
    )
    _print_result("张三 第1轮: case30建网+潮流+过载分析", zs_r1)


    ls_r1 = agent.invoke(
        {"messages": [HumanMessage("你好，请用 57 节点电网进行潮流计算，然后进行 N-1 安全校核分析，给我结果。")]},
        config=cfg_lisi
    )
    _print_result("李四 第1轮: case57潮流+N-1校核（新会话，独立case57电网）", ls_r1)


    zs_r3 = agent.invoke(
        {"messages": [HumanMessage("之前我的 case30 是 1.8 倍负荷，现在再做一个 N-1 校核，只看前 10 条线路。")]},
        config=cfg_zhangsan
    )
    _print_result("张三 第3轮: N-1校核前10条线（自动找回之前1.8倍负荷的case30）", zs_r3)