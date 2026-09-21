# -*- coding: utf-8 -*-
"""
会话表的 CRUD 封装
所有DB操作都在这一层，Service 不直接碰 SQLAlchemy
写操作统一用单条 SQL，避免先 SELECT 再 UPDATE 的两次交互
"""
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from .PowerSession import PowerSession


class SessionRepository:
    """会话仓库：所有对 power_sessions 表的操作都在这"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============== 查 ==============

    async def get_by_id(self, session_id: str) -> Optional[PowerSession]:
        """按ID查单个会话"""
        stmt = select(PowerSession).where(PowerSession.id == session_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[PowerSession]:
        """
        会话列表：按最后更新时间倒序（最近聊过的在最上面）
        user_id 传 None 就查全部（当前单用户场景）
        """
        stmt = select(PowerSession)
        if user_id:
            stmt = stmt.where(PowerSession.user_id == user_id)
        stmt = stmt.order_by(PowerSession.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ============== 增 ==============

    async def create(
        self,
        session_id: str,
        name: str = "新会话",
        user_id: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> PowerSession:
        """新建一个会话记录"""
        powerSession = PowerSession(
            id=session_id,
            name=name or "新会话",
            user_id=user_id or "default",
            message_count=0,
            last_message=None,
        )
        if config:
            powerSession.set_config(config)
        self.db.add(powerSession)
        await self.db.flush()
        return powerSession

    # ============== 改（全用单条 SQL） ==============

    async def update_name(self, session_id: str, new_name: str) -> bool:
        """修改会话名称"""
        stmt = (
            update(PowerSession)
            .where(PowerSession.id == session_id)
            .values(name=new_name[:128])
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def update_config(self, session_id: str, config: dict) -> bool:
        """修改会话配置（全量覆盖，调用方自己传完整的）"""
        stmt = (
            update(PowerSession)
            .where(PowerSession.id == session_id)
            .values(config_json=self._dump_json(config))
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def update_grid_meta(self, session_id: str, meta: dict) -> bool:
        """更新电网恢复元信息"""
        stmt = (
            update(PowerSession)
            .where(PowerSession.id == session_id)
            .values(grid_meta_json=self._dump_json(meta))
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def update_last_message(
        self,
        session_id: str,
        message_preview: str,
        delta_count: int = 1,
    ) -> bool:
        """
        每次聊天结束调用：
        - 刷新"最后一条消息预览"（只留前500字给列表展示）
        - 累加消息数（SQL 层面 +delta_count，避免并发不准）
        """
        stmt = (
            update(PowerSession)
            .where(PowerSession.id == session_id)
            .values(
                last_message=message_preview[:500] if message_preview else None,
                message_count=PowerSession.message_count + delta_count,
            )
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def reset_count_and_preview(self, session_id: str) -> bool:
        """重置会话电网时调用（清空消息预览 + 电网元信息，消息数保留）"""
        stmt = (
            update(PowerSession)
            .where(PowerSession.id == session_id)
            .values(last_message=None, grid_meta_json=self._dump_json({}))
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    # ============== 删 ==============

    async def soft_delete(self, session_id: str) -> bool:
        """删除会话（物理移除）"""
        stmt = delete(PowerSession).where(PowerSession.id == session_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    # ============== 内部工具 ==============

    @staticmethod
    def _dump_json(data: dict) -> str:
        """把 dict 序列化为 JSON 字符串（ensure_ascii=False 保留中文）"""

        return json.dumps(data, ensure_ascii=False)