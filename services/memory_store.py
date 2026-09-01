# -*- coding: utf-8 -*-
"""
简易内存降级存储：当 MySQL 不可用时使用（保证前端至少能试用）
数据存进程内存，服务重启即丢失。
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from schemas import SessionConfig


class MemorySessionStore:
    """用进程级字典实现的极简会话存储（MySQL 挂掉时的兜底）"""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    def create(self, name: str, config: Optional[Dict] = None) -> Dict[str, Any]:
        """新建会话，返回与 SessionRepository.to_summary_dict 同构的 dict"""
        sid = uuid.uuid4().hex
        now = datetime.now().isoformat()
        row = {
            "id": sid,
            "name": name or "新会话",
            "last_message": "",
            "message_count": 0,
            "created_at": now,
            "updated_at": now,
            "config": config or SessionConfig().model_dump(),
        }
        self._sessions[sid] = row
        return row

    def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """会话列表，按最近使用排序"""
        return sorted(
            list(self._sessions.values()),
            key=lambda x: x.get("updated_at", ""),
            reverse=True,
        )[:limit]

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def update(
        self,
        session_id: str,
        name: Optional[str] = None,
        config: Optional[Dict] = None,
    ) -> bool:
        """改名称/配置，哪个传了改哪个"""
        row = self._sessions.get(session_id)
        if row is None:
            return False
        changed = False
        if name is not None:
            row["name"] = name
            changed = True
        if config is not None:
            row["config"] = config
            changed = True
        if changed:
            row["updated_at"] = datetime.now().isoformat()
        return changed

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def touch(
        self,
        session_id: str,
        last_message: Optional[str] = None,
        delta_count: int = 0,
    ) -> None:
        """聊天结束后刷新预览和消息数（降级模式）"""
        row = self._sessions.get(session_id)
        if row is None:
            return
        if last_message is not None:
            row["last_message"] = last_message[:500]
        row["message_count"] = row.get("message_count", 0) + delta_count
        row["updated_at"] = datetime.now().isoformat()

    def clear_preview(self, session_id: str) -> None:
        """重置电网时清空最后消息预览"""
        row = self._sessions.get(session_id)
        if row is not None:
            row["last_message"] = ""
            row["updated_at"] = datetime.now().isoformat()


# 全局单例：所有 controller 降级时共用这一份
memory_sessions = MemorySessionStore()
