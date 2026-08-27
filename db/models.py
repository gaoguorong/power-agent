# -*- coding: utf-8 -*-
"""
数据库 ORM 模型
目前只有一张会话表：存业务元数据（名称/配置/电网恢复元信息等）
注意：LangGraph 自己的消息历史（checkpoint）存在本地 SQLite，不在这里
两者通过 id = session_id = thread_id 一一对应
"""
import json
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .mysql import Base


class PowerSession(Base):
    """
    智能体会话业务元数据表
    兼容 MySQL 5.1+：不用 JSON 类型、不用 DATETIME DEFAULT CURRENT_TIMESTAMP
    数据库列名全部大写
    """
    __tablename__ = "POWER_SESSIONS"

    # 会话ID：同时作为 LangGraph 的 thread_id 和 SqliteSaver 的 key
    id: Mapped[str] = mapped_column("ID", String(64), primary_key=True, comment="会话ID=LangGraph thread_id")

    # 展示名称，前端可编辑
    name: Mapped[str] = mapped_column("NAME", String(128), default="新会话", comment="会话名称")

    # 预留多用户字段，现在全部填 'default' 也行
    user_id: Mapped[str | None] = mapped_column("USER_ID", String(64), default=None, comment="用户ID（预留）")

    # ----- 下面两个字段用 Text 存 JSON，兼容性更好（MySQL<5.7 不支持 JSON 类型） -----
    # 会话级配置：{ default_grid_type, ui_theme, ui_max_table_rows ... }
    config_json: Mapped[str | None] = mapped_column("CONFIG_JSON", Text, default=None, comment="会话配置(JSON字符串)")

    # 电网恢复元信息：服务重启后靠这个恢复电网对象
    # 例：{ "last_grid_type": "case30", "load_factor": 1.8, "has_pf_result": true }
    grid_meta_json: Mapped[str | None] = mapped_column("GRID_META_JSON", Text, default=None, comment="电网恢复元信息(JSON字符串)")

    # 会话列表上展示的小摘要
    last_message: Mapped[str | None] = mapped_column("LAST_MESSAGE", String(500), default=None, comment="最后一条消息预览")
    message_count: Mapped[int] = mapped_column("MESSAGE_COUNT", Integer, default=0, comment="消息总数")

    # 时间戳：兼容 MySQL 5.1，时间戳由 Python 代码写入
    created_at: Mapped[datetime] = mapped_column(
        "CREATED_AT",
        DateTime,
        default=datetime.now,
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "UPDATED_AT",
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        comment="最后更新时间"
    )
    deleted_at: Mapped[datetime | None] = mapped_column("DELETED_AT", DateTime, default=None, comment="软删除时间")

    # ======================================================
    # 下面是两个方便读写 JSON 的小工具方法，不用手动 dumps/loads
    # ======================================================

    def get_config(self) -> dict:
        """读取 config_json 并转为字典"""
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_config(self, cfg: dict):
        """把字典存成 JSON 字符串"""
        self.config_json = json.dumps(cfg, ensure_ascii=False)

    def get_grid_meta(self) -> dict:
        """读取电网恢复元信息"""
        if not self.grid_meta_json:
            return {}
        try:
            return json.loads(self.grid_meta_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_grid_meta(self, meta: dict):
        """保存电网恢复元信息"""
        self.grid_meta_json = json.dumps(meta, ensure_ascii=False)

    def to_summary_dict(self) -> dict:
        """转成会话列表需要的简洁格式"""
        return {
            "id": self.id,
            "name": self.name,
            "last_message": self.last_message or "",
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "config": self.get_config(),
        }