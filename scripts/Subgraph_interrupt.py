from langgraph.graph import START, StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from typing_extensions import TypedDict

class State(TypedDict):
    foo: str

# 子图
def subgraph_node_1(state: State):
    print("中断前subgraph_node_1 ")
    value = interrupt("Provide value:")
    print("中断后subgraph_node_1 :", value)
    return {"foo": state["foo"] + value}

def subgraph_node_2(state: State):
    print("subgraph_node_2")

subgraph_builder = StateGraph(State)
subgraph_builder.add_node(subgraph_node_1)
subgraph_builder.add_node(subgraph_node_2)
subgraph_builder.add_edge(START, "subgraph_node_1")
subgraph_builder.add_edge("subgraph_node_1", "subgraph_node_2")

subgraph = subgraph_builder.compile()

# 父图
builder = StateGraph(State)
builder.add_node("node_1", subgraph)
builder.add_edge(START, "node_1")

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "1"}}

graph.invoke({"foo": ""}, config)
parent_state = graph.get_state(config)

# 这仅在子图被中断时可用。
# 一旦您恢复图，您将无法访问子图状态。
graph_steate = graph.get_state(config, subgraphs=True)
# print(graph_steate)
subgraph_state = graph.get_state(config, subgraphs=True).tasks[0].state

# 恢复子图
result = input("请输入恢复子图的内容：\n")
# graph.invoke(Command(resume="bar"), config)
graph.invoke(Command(resume=result), config)
