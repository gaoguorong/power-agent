import uuid

from typing_extensions import TypedDict, NotRequired
from langgraph.graph import StateGraph, START, END

from langgraph.checkpoint.memory import InMemorySaver
from agents.llm_client import create_llm
llm = create_llm()


class State(TypedDict):
    topic: NotRequired[str]
    joke: NotRequired[str]

def generate_topic(state: State):
    """LLM调用来生成笑话主题"""
    msg = llm.invoke("Give me a funny topic for a joke")
    return {"topic": msg.content}


def write_joke(state: State):
    """LLM调用来基于主题写笑话"""
    msg = llm.invoke(f"Write a short joke about {state['topic']}")
    return {"joke": msg.content}


# 构建工作流
workflow = StateGraph(State)

# 添加节点
workflow.add_node("generate_topic", generate_topic)
workflow.add_node("write_joke", write_joke)

# 添加边连接节点
workflow.add_edge(START, "generate_topic")
workflow.add_edge("generate_topic", "write_joke")
workflow.add_edge("write_joke", END)

# 编译
checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

config  = {"configurable": {"thread_id": str(uuid.uuid4())}}

state = graph.invoke({}, config=config)
# print(state)
# print(state["topic"])
# print(state["joke"])

# 状态以倒序时间顺序返回。
states = list(graph.get_state_history(config))

for state in states:
    print(state.next)
    print(state.config["configurable"]["thread_id"])
    print(state.config["configurable"]["checkpoint_id"])


selected_stated = states[1]
print(f"selected_stated.next: {selected_stated.next}")
print(f"selected_stated.values: {selected_stated.values}")
print(selected_stated.config["configurable"]["checkpoint_id"])
print(f"selected_stated.config: {selected_stated.config}")

new_config = graph.update_state(selected_stated.config,values={"topic":"chickens"})
print(f"new_config: {new_config}")

state_new = graph.invoke(None, new_config)
print(f"state_new: {state_new}")
print(f"state_new['topic']: {state_new['topic']}")
print(f"state_new['joke']: {state_new['joke']}")


for state in list(graph.get_state_history(new_config)):
    print(state.next)
    print(state.config["configurable"]["checkpoint_id"])
    print()

print("-----------------")

for state in list(graph.get_state_history(config)):
    print(state.next)
    print(state.config["configurable"]["checkpoint_id"])
    print()