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
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage

from llm_client import LLMClient
from tools.langchain_tool import ALL_TOOLS, query_knowledge


llm_client = LLMClient()
llm = llm_client.llm

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
    "【注意事项】\n"
    "· 任何计算类工具之前，必须先调用 create_test_grid（或 run_full_analysis 内部已包含），否则会报错。\n"
    "· 如果用户说的是'刚才/之前/继续'这类指代词，说明是多轮对话的延续，请基于之前的工具结果继续。\n"
    "· 工具返回 success=False 时，请把错误信息清晰告知用户，不要瞎编结果。\n"
    "· 输出最终回答时，请用简洁的中文总结关键数据，不要把工具返回的大段 JSON 原样复制。"
)

def agent_node(state: AgentState):
    messages_with_sys = [("system", SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages_with_sys)
    return {"messages": [response]}

# ============================================================
# 3. inject_session 节点：把 State 里的 session_id 注入到每个 tool_call 的 args
#    （LLM 不知道有 session_id 这个参数，需要引擎端塞进去）
# ============================================================
def inject_session_node(state: AgentState):
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            if "args" not in tc:
                tc["args"] = {}
            tc["args"]["session_id"] = state.get("session_id", "default")
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

agent = graph.compile()


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
    SESSION = "test-session-001"

    # 场景 1：潮流计算->N-1安全校核分析
    # r1 = agent.invoke({
    #     "messages": [("human", "你好，请进行潮流计算，然后进行N-1安全校核分析。")],
    #     "session_id": SESSION,
    # })
    # _print_result("场景1工具潮流计算, N-1安全校核分析", r1)

    # 场景 2：多轮分步（A模式）—— 建电网 → 缩放负荷 → 看过载 → 出风险报告
    r2 = agent.invoke({
        "messages": [("human", "我想把30节点电网负荷调高2倍，先计算潮流计算，然后看下N-1安全校核结果")],
        "session_id": SESSION
    })
    _print_result("场景2 多轮复杂", r2)  # 场景2 多轮复杂
    #
    # # 场景 3：知识问答（C模式）—— 不调任何计算工具
    # r3 = agent.invoke({
    #     "messages": [("human", "什么是 N-1 准则？电压正常范围一般是多少？")],
    #     "session_id": SESSION,
    # })
    # _print_result("场景3 知识问答 C模式", r3)