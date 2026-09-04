# -*- coding: utf-8 -*-
"""
自包含版 demo：对话记忆的【建表 / 存 / 取】全部写在本文件里，用 pymysql 显式执行 SQL。
不依赖 langgraph-checkpoint-mysql 的内部黑盒表——你能一眼看懂“建什么表、建到哪、怎么存怎么读”。

流程：建表 chat_memory → 每轮：存用户消息 → 读回全部历史 → 喂给 LangGraph 图 → 存 AI 回复。
"""
import pymysql
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, START
from agents.llm_client import create_llm

# ===== MySQL 连接参数（表建到 power_agent 库）=====
DB = dict(host="localhost", port=3306, user="root", password="Taylor081930",
          database="power_agent", charset="utf8mb4", autocommit=True)
THREAD_ID = "1"          # 记忆键：同一个 thread_id = 同一段对话

llm = create_llm()

# ===== 1) 建表 SQL：就写在这里，一目了然（建到上面 DB['database'] 指定的库）=====
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_memory (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    thread_id  VARCHAR(64) NOT NULL,          -- 会话/记忆键
    role       VARCHAR(16) NOT NULL,          -- user / assistant
    content    TEXT        NOT NULL,          -- 消息内容
    created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    KEY idx_thread (thread_id)
);
"""


# ===== 2) 存：把一条消息 INSERT 进 MySQL =====
def save_message(conn, role, content):
    sql = "INSERT INTO chat_memory (thread_id, role, content) VALUES (%s, %s, %s)"
    with conn.cursor() as cur:
        cur.execute(sql, (THREAD_ID, role, content))


# ===== 3) 取：按 thread_id 从 MySQL 读回全部历史 =====
def load_history(conn):
    sql = "SELECT role, content FROM chat_memory WHERE thread_id=%s ORDER BY id"
    with conn.cursor() as cur:
        cur.execute(sql, (THREAD_ID,))
        rows = cur.fetchall()
    # 转成 LangChain 消息对象：user→HumanMessage，assistant→AIMessage
    return [HumanMessage(c) if r == "user" else AIMessage(c) for r, c in rows]


# ===== LangGraph 图：唯一节点 call_model（不挂 checkpointer，记忆完全由我们自己的表管）=====
def call_model(state: MessagesState):
    return {"messages": llm.invoke(state["messages"])}


builder = StateGraph(MessagesState)
builder.add_node(call_model)
builder.add_edge(START, "call_model")
graph = builder.compile()


def main():
    conn = pymysql.connect(**DB)
    try:
        # 建表（幂等：已存在就跳过）
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        print(f"表 chat_memory 已就绪（建在 {DB['database']} 库）\n")

        for user_text in ("hi! I'm bob", "what's my name?"):
            print(f"user: {user_text}")
            save_message(conn, "user", user_text)          # 存：用户消息入库
            history = load_history(conn)                   # 取：读回全部历史（含之前对话）
            result = graph.invoke({"messages": history})   # 喂给图 → LLM
            ai_text = result["messages"][-1].content
            save_message(conn, "assistant", ai_text)       # 存：AI 回复入库
            print(f"ai  : {ai_text}\n")

        # 最后把表里真实内容打印出来，眼见为实
        print("==== chat_memory 表最终内容（直接从 MySQL 查）====")
        with conn.cursor() as cur:
            cur.execute("SELECT id, thread_id, role, content FROM chat_memory ORDER BY id")
            for row in cur.fetchall():
                print(row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
