# -*- coding: utf-8 -*-
"""
LangGraph + MySQL 持久化最小 demo —— 重点：看清“对话记忆是怎么存进 MySQL 的”。

一句话原理：每次调用图 =【按 thread_id 从 MySQL 读回历史】→【跑 LLM 节点】→【把新状态写回 MySQL】。
建表、读、写全部由 checkpointer(PyMySQLSaver) 在库内部自动完成，本脚本不写一行 SQL。
"""
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver
from langgraph.graph import StateGraph, MessagesState, START
from agents.llm_client import create_llm

# mysql://用户:密码@主机:端口/库名（库要先存在，需 MySQL 8.0+）
DB_URI = "mysql://root:Taylor081930@localhost:3306/power_agent"
THREAD_ID = "1"          # 记忆键：thread_id 相同 = 同一段对话，历史会不断累积

llm = create_llm()


def call_model(state: MessagesState):
    """图里唯一的节点：把当前全部消息发给 LLM，返回它的回复。"""
    return {"messages": llm.invoke(state["messages"])}


def show_whats_stored(graph, config):
    """从 MySQL 读回并打印“现在存了什么”，让你直观看到持久化结果。"""
    snapshot = graph.get_state(config)                          # ← 从 MySQL 读最新状态
    msgs = snapshot.values["messages"]
    n = len(list(graph.get_state_history(config)))              # ← 从 MySQL 读全部检查点
    print(f"   ↳ MySQL 现存 {len(msgs)} 条消息、累计 {n} 个检查点：")
    for m in msgs:
        print(f"     [{m.type}] {m.content}")


# 连接 MySQL（with 结束自动关连接）
with PyMySQLSaver.from_conn_string(DB_URI) as checkpointer:
    # ① 首次运行自动建表：checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations（幂等）
    checkpointer.setup()

    # ② 建图并挂上 checkpointer —— 挂了它，图才会在每步自动读写 MySQL
    builder = StateGraph(MessagesState)
    builder.add_node(call_model)
    builder.add_edge(START, "call_model")
    graph = builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": THREAD_ID}}

    # ③ 第 1 轮：告诉它我叫 bob（invoke 内部：读历史 → 跑 LLM → 写回 MySQL）
    print("第1轮  user: hi! I'm bob")
    graph.invoke({"messages": [{"role": "user", "content": "hi! I'm bob"}]}, config)
    show_whats_stored(graph, config)

    # ④ 第 2 轮：问我叫什么。它能答对，正是因为第1轮已存进 MySQL、这轮又被读了回来
    print("\n第2轮  user: what's my name?")
    graph.invoke({"messages": [{"role": "user", "content": "what's my name?"}]}, config)
    show_whats_stored(graph, config)
