from typing_extensions import TypedDict
from langgraph.graph.state import StateGraph, START,END

from agents.llm_client import create_llm
llm = create_llm()

# 定义父图
class State(TypedDict):
    foo: str

def node_1(state: State):
    return {"foo": "node1 " + state["foo"]}

def node_2(state: State):
    return {"foo": "node2 " + state["foo"]}

builder = StateGraph(State)
builder.add_node("node_1", node_1)
builder.add_node("node_2", node_2)
builder.add_edge(START, "node_1")
builder.add_edge("node_1", "node_2")
builder.add_edge("node_2", END)

graph = builder.compile()

for chunk in graph.stream(
    {"foo": "1"},
    stream_mode="updates",
):
    print(chunk)