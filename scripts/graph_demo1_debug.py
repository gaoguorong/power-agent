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
    msg = llm.invoke("Give me a funny topic for a joke")
    return {"topic": msg.content}


def write_joke(state: State):
    msg = llm.invoke(f"Write a short joke about {state['topic']}")
    return {"joke": msg.content}


workflow = StateGraph(State)
workflow.add_node("generate_topic", generate_topic)
workflow.add_node("write_joke", write_joke)
workflow.add_edge(START, "generate_topic")
workflow.add_edge("generate_topic", "write_joke")
workflow.add_edge("write_joke", END)

checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

config  = {"configurable": {"thread_id": str(uuid.uuid4())}}
print("=" * 80)
print(f"[初始 config] thread_id = {config['configurable']['thread_id']}")
print("=" * 80)

state = graph.invoke({}, config=config)

print("\n========== 第一次遍历: get_state_history(config) ==========")
for i, state in enumerate(list(graph.get_state_history(config))):
    print(f"[{i}] next={state.next}")
    print(f"    thread_id   = {state.config['configurable']['thread_id']}")
    print(f"    checkpoint  = {state.config['configurable']['checkpoint_id']}")
    print()

selected_stated = list(graph.get_state_history(config))[1]
print(f"[选中 states[1]] checkpoint = {selected_stated.config['configurable']['checkpoint_id']}")
print(f"                thread_id   = {selected_stated.config['configurable']['thread_id']}")

print("\n>>> 调用 update_state")
new_config = graph.update_state(selected_stated.config, values={"topic":"chickens"})
print(f"[返回的 new_config] thread_id    = {new_config['configurable']['thread_id']}")
print(f"                    checkpoint_ns= {new_config['configurable'].get('checkpoint_ns')}")
print(f"                    checkpoint_id= {new_config['configurable']['checkpoint_id']}")

print("\n>>> 调用 graph.invoke(None, new_config)")
state_new = graph.invoke(None, new_config)
print(f"[invoke 完成后 state_new.config 的 thread_id 我们无法直接看到，用下面方法验证]")
print(f"[实际上 invoke 返回的是 state values，不是 config]")

print("\n========== 用原 config 遍历: get_state_history(config) ==========")
print(f"[config thread_id = {config['configurable']['thread_id']}]")
for i, state in enumerate(list(graph.get_state_history(config))):
    print(f"[{i}] next={state.next}")
    print(f"    thread_id   = {state.config['configurable']['thread_id']}")
    print(f"    checkpoint  = {state.config['configurable']['checkpoint_id']}")
    print()

print("\n========== 用 new_config 遍历: get_state_history(new_config) ==========")
print(f"[new_config thread_id = {new_config['configurable']['thread_id']}]")
for i, state in enumerate(list(graph.get_state_history(new_config))):
    print(f"[{i}] next={state.next}")
    print(f"    thread_id   = {state.config['configurable']['thread_id']}")
    print(f"    checkpoint  = {state.config['configurable']['checkpoint_id']}")
    print()

print("\n========== 直接用 graph.get_state 查询最后那个 checkpoint 属于谁 ==========")
# 手动找 invoke(None, new_config) 产生的新 END checkpoint（也就是原 config 遍历的第0个）
all_by_config = list(graph.get_state_history(config))
last_end_cp_id = all_by_config[0].config['configurable']['checkpoint_id']
last_end_thread_id = all_by_config[0].config['configurable']['thread_id']
print(f"[新路线最后那个 END checkpoint]")
print(f"    checkpoint_id = {last_end_cp_id}")
print(f"    它的 thread_id = {last_end_thread_id}")
print(f"    原 config 的 tid= {config['configurable']['thread_id']}")
print(f"    new_config tid= {new_config['configurable']['thread_id']}")
print(f"    和谁相等？ → 原config: {last_end_thread_id == config['configurable']['thread_id']}  new_config: {last_end_thread_id == new_config['configurable']['thread_id']}")