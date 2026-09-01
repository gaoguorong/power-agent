# -*- coding: utf-8 -*-
"""
M 层：数据持久化层
负责：MySQL 连接、ORM 模型定义、会话 CRUD 封装
- database           ：异步引擎 / 会话工厂 / Base / 建表
- session            ：PowerSession ORM 模型
- session_message    ：SessionMessages 消息历史表（聊天记录持久化）
- session_repository ：会话表 CRUD 封装
"""
from .database import (
    engine,
    Base,
    AsyncSessionLocal,
    get_db_session,
    create_all_tables,
)
from .session import PowerSession
from .session_message import SessionMessages
from .session_repository import SessionRepository

__all__ = [
    "engine",
    "Base",
    "AsyncSessionLocal",
    "get_db_session",
    "create_all_tables",
    "PowerSession",
    "SessionMessages",
    "SessionRepository",
]
