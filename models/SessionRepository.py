# -*- coding: utf-8 -*-
"""
会话表的 CRUD 封装
让接口代码里不要直接写 SQLAlchemy 查询，所有DB操作都放这里
写法尽量简单直白，每个方法只干一件事
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .PowerSession import PowerSession


class SessionRepository:
    """会话仓库：所有对 power_sessions 表的操作都在这"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============== 查 ==============

    async def get_by_id(self, session_id: str) -> Optional[PowerSession]:
        """按ID查单个会话（排除已软删的）"""
        stmt = select(PowerSession).where(
            PowerSession.id == session_id,
            PowerSession.deleted_at.is_(None)
        )
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
        stmt = select(PowerSession).where(PowerSession.deleted_at.is_(None))
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
        row = PowerSession(
            id=session_id,
            name=name or "新会话",
            user_id=user_id or "default",
            message_count=0,
            last_message=None,
        )
        if config:
            row.set_config(config)
        self.db.add(row)
        await self.db.flush()  # 让 id 等默认值生效
        return row

    # ============== 改 ==============

    async def update_name(self, session_id: str, new_name: str) -> bool:
        """修改会话名称"""
        row = await self.get_by_id(session_id)
        if not row:
            return False
        row.name = new_name[:128]  # 防超长
        return True

    async def update_config(self, session_id: str, config: dict) -> bool:
        """修改会话配置（全量覆盖，调用方自己传完整的）"""
        row = await self.get_by_id(session_id)
        if not row:
            return False
        row.set_config(config)
        return True

    async def update_grid_meta(self, session_id: str, meta: dict) -> bool:
        """更新电网恢复元信息"""
        row = await self.get_by_id(session_id)
        if not row:
            return False
        row.set_grid_meta(meta)
        return True

    async def update_last_message(
        self,
        session_id: str,
        message_preview: str,
        delta_count: int = 1,
    ) -> bool:
        """
        每次聊天结束调用：
        - 刷新"最后一条消息预览"（只留前500字给列表展示）
        - 累加消息数
        """
        row = await self.get_by_id(session_id)
        if not row:
            return False
        if message_preview:
            row.last_message = message_preview[:500]
        row.message_count = max(0, row.message_count + delta_count)
        return True

    async def reset_count_and_preview(self, session_id: str) -> bool:
        """重置会话电网时调用（清空消息预览，消息数保留）"""
        row = await self.get_by_id(session_id)
        if not row:
            return False
        row.last_message = None
        row.set_grid_meta({})  # 电网元信息也清空
        return True

    # ============== 删（软删） ==============
    async def soft_delete(self, session_id: str) -> bool:
        """软删除：不真删行，只是打个时间戳"""
        row = await self.get_by_id(session_id)
        if not row:
            return False
        row.deleted_at = datetime.now()
        return True