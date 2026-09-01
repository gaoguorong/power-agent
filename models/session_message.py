# -*- coding: utf-8 -*-
"""
会话消息历史表：消息持久化
GraphService 内存里的消息历史每轮聊天结束后落到这里，
服务重启 / 刷新页面 / 点击历史会话时靠它恢复聊天记录。
与 POWER_SESSIONS 通过 SESSION_ID 一一对应。
"""
from datetime import datetime
from sqlalchemy import String, DateTime, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SessionMessages(Base):
    """
    一个会话一行：完整消息历史以 JSON 数组存放
    （含 user/assistant/tool 三类，assistant 带 tool_calls）
    """
    __tablename__ = "POWER_SESSION_MESSAGES"

    session_id: Mapped[str] = mapped_column(
        "SESSION_ID", String(64), primary_key=True, comment="会话ID"
    )

    # 用 MEDIUMTEXT（16MB）：工具输出的 JSON 可能很大，普通 TEXT 64KB 不够
    messages_json: Mapped[str | None] = mapped_column(
        "MESSAGES_JSON",
        Text().with_variant(MEDIUMTEXT(), "mysql"),
        default=None,
        comment="完整消息历史(JSON数组)",
    )

    updated_at: Mapped[datetime] = mapped_column(
        "UPDATED_AT",
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        comment="最后更新时间",
    )
