# -*- coding: utf-8 -*-
"""
手动初始化 langgraph-checkpoint-mysql 所需的 4 张表。
用于 MySQL < 8.0.13 不支持 JSON DEFAULT 的环境。

用法:
    python scripts/init_checkpoint_tables.py
"""
import asyncio
import aiomysql
from config.mysql_config import DATABASE_CONFIG

INIT_SQLS = [
    """
    CREATE TABLE IF NOT EXISTS checkpoint_migrations (
        v INTEGER PRIMARY KEY
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id VARCHAR(150) NOT NULL,
        checkpoint_ns VARCHAR(150) NOT NULL DEFAULT '',
        checkpoint_id VARCHAR(150) NOT NULL,
        parent_checkpoint_id VARCHAR(150),
        type VARCHAR(150),
        checkpoint JSON NOT NULL,
        metadata JSON NOT NULL,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_blobs (
        thread_id VARCHAR(150) NOT NULL,
        checkpoint_ns VARCHAR(150) NOT NULL DEFAULT '',
        channel VARCHAR(150) NOT NULL,
        version VARCHAR(150) NOT NULL,
        type VARCHAR(150) NOT NULL,
        `blob` LONGBLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id VARCHAR(150) NOT NULL,
        checkpoint_ns VARCHAR(150) NOT NULL DEFAULT '',
        checkpoint_id VARCHAR(150) NOT NULL,
        task_id VARCHAR(150) NOT NULL,
        idx INTEGER NOT NULL,
        channel VARCHAR(150) NOT NULL,
        type VARCHAR(150),
        `blob` LONGBLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    );
    """,
    "INSERT INTO checkpoint_migrations (v) VALUES (1)",
]


async def main():
    from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
    conn_kwargs = AIOMySQLSaver.parse_conn_string(DATABASE_CONFIG["mysql_url"])
    conn = await aiomysql.connect(**conn_kwargs, autocommit=True)
    async with conn.cursor() as cur:
        for sql in INIT_SQLS:
            sql = sql.strip()
            print(f"[执行] {sql.splitlines()[0][:60]}...")
            await cur.execute(sql)
    conn.close()
    await conn.wait_closed()
    print("✅ checkpoint 表初始化完成，启动服务后 setup() 会从 Migration 2 继续升级")


if __name__ == "__main__":
    asyncio.run(main())