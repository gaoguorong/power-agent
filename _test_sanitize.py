# -*- coding: utf-8 -*-
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agents.graph_agent import _sanitize_tool_call_history

# 模拟崩溃后残留的历史：AIMessage 有 tool_calls，但缺少对应 ToolMessage
broken_history = [
    HumanMessage(content="生成2个场景"),
    AIMessage(
        content="",
        tool_calls=[{
            "id": "call_001",
            "name": "lasch_submit_workflow",
            "args": {"time_window_start": "2025-10-03 17:00:00",
                     "time_window_end": "2025-10-03 21:00:00",
                     "scenario_count": 2},
        }],
    ),
    HumanMessage(content="再生成2个场景"),
]

print("=== 清理前 ===")
for m in broken_history:
    tcs = getattr(m, "tool_calls", None)
    print("  %s: tool_calls=%s" % (type(m).__name__, tcs))

changed = _sanitize_tool_call_history(broken_history)
print("\n是否有修改: %s" % changed)

print("\n=== 清理后 ===")
for m in broken_history:
    tcs = getattr(m, "tool_calls", None)
    print("  %s: tool_calls=%s" % (type(m).__name__, tcs))

print("\n=== 验证 ===")
all_tool_ids = set()
for m in broken_history:
    if isinstance(m, ToolMessage):
        all_tool_ids.add(getattr(m, "tool_call_id", None))

ok = True
for m in broken_history:
    if isinstance(m, AIMessage):
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc.get("id") not in all_tool_ids:
                ok = False
                print("  FAIL: tool_call %s 没有对应 ToolMessage" % tc.get("id"))
print("  校验结果: %s" % ("PASS" if ok else "FAIL"))

# 再测：正常配对的历史不应被修改
normal_history = [
    HumanMessage(content="你好"),
    AIMessage(
        content="",
        tool_calls=[{"id": "call_a", "name": "tool_a", "args": {}}],
    ),
    ToolMessage(content="ok", name="tool_a", tool_call_id="call_a"),
]
changed2 = _sanitize_tool_call_history(normal_history)
print("\n正常历史是否被误改: %s (期望 False)" % changed2)
assert changed2 is False, "正常历史不应被修改"
print("  PASS")