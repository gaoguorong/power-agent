# -*- coding: utf-8 -*-
"""
会话业务服务层：把【MySQL 业务元数据】和【GraphAgent 内存状态】串起来。
接口层只调这里的方法，不关心底层是写 MySQL 还是操作内存电网对象。

注意：每个请求会 new 一个 SessionService（db session 是请求级别的），
     而 GraphService 是全局单例，底层共享同一个 GraphAgent。

事务边界：统一由 models.database.get_db_session 管控，
         本层和 Repository 层都不写 commit/rollback。
"""
import json
import uuid
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.SessionRepository import SessionRepository
from models.PowerSession import PowerSession
from schemas import SessionConfig, SessionCreateRequest, SessionUpdateRequest
from config.model_config import SUPPORTED_GRID_TYPES
from tools.langchain_tool import get_grid_tools_obj
from .graph_service import GraphService

_SUPPORTED_GRIDS = set(SUPPORTED_GRID_TYPES)


class SessionService:
    """会话 CRUD + 电网对象的懒加载/恢复"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = SessionRepository(db)
        self.graph_service = GraphService.get_instance()

    # ==========================================================
    # 1. 新建会话
    # ==========================================================
    async def create_session(
        self,
        req: SessionCreateRequest,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新建会话：MySQL 插一条元数据；若配置了默认电网就顺手创建好"""
        session_id = uuid.uuid4().hex
        cfg_dict = req.config.model_dump() if req.config else SessionConfig().model_dump()

        powerSession = await self.session_repo.create(
            session_id=session_id,
            name=req.name,
            user_id=user_id,
            config=cfg_dict,
        )

        grid_type = cfg_dict.get("default_grid_type")
        if grid_type and grid_type in _SUPPORTED_GRIDS:
            try:
                self._ensure_grid_loaded(session_id, grid_type, load_factor=1.0)
            except Exception:
                pass  # 预建失败不影响会话，用户提问时 LLM 会自己调 create_test_grid

        return powerSession.to_summary_dict()

    # ==========================================================
    # 2. 查询会话
    # ==========================================================
    async def list_sessions(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """会话列表（侧边栏用），按最近使用排序"""
        powerSessions: List[PowerSession] = await self.session_repo.list_all(user_id=user_id, limit=limit)
        return [powerSession.to_summary_dict() for powerSession in powerSessions]

    async def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        """单个会话详情 = MySQL 元数据 + 消息历史（刷新页面恢复用）"""
        powerSession = await self.session_repo.get_by_id(session_id)
        if not powerSession:
            return None
        await self._restore_grid_if_needed(powerSession)

        return {
            "id": powerSession.id,
            "name": powerSession.name,
            "created_at": powerSession.created_at.isoformat() if powerSession.created_at else None,
            "updated_at": powerSession.updated_at.isoformat() if powerSession.updated_at else None,
            "config": powerSession.get_config(),
            "messages": await self.graph_service.get_session_messages(session_id),
        }

    # ==========================================================
    # 3. 修改会话
    # ==========================================================
    async def update_session(self, session_id: str, req: SessionUpdateRequest) -> bool:
        """修改会话：name / config 哪个传了改哪个"""
        changed = False
        if req.name is not None:
            changed = await self.session_repo.update_name(session_id, req.name) or changed
        if req.config is not None:
            changed = await self.session_repo.update_config(session_id, req.config.model_dump()) or changed
        return changed

    async def update_grid_meta_to_db(self, session_id: str) -> None:
        """每次工具调用完，把内存电网对象的元信息刷到 MySQL（服务重启后靠它恢复）"""
        meta = self.graph_service.get_session_grid_meta(session_id)
        if meta:
            await self.session_repo.update_grid_meta(session_id, meta)

    async def update_last_message(
        self,
        session_id: str,
        ai_text: str,
        delta_count: int = 2,  # 一问一答 = 两条消息
    ) -> None:
        """聊天结束后更新消息数和最后一条预览"""
        await self.session_repo.update_last_message(session_id, ai_text, delta_count=delta_count)

    # ==========================================================
    # 4. 删除会话 & 重置电网
    # ==========================================================
    async def delete_session(self, session_id: str) -> bool:
        """删除会话：MySQL 硬删 + 清内存电网对象"""
        ok_ = await self.session_repo.soft_delete(session_id)
        self.graph_service.reset_grid_session(session_id)
        return ok_

    async def reset_grid(self, session_id: str) -> bool:
        """重置会话电网：清内存对象 + 清 MySQL 元数据，对话历史保留"""
        row = await self.session_repo.get_by_id(session_id)
        if not row:
            return False
        self.graph_service.reset_grid_session(session_id)
        await self.session_repo.reset_count_and_preview(session_id)
        return True

    # ==========================================================
    # 内部：电网对象的懒加载 / 恢复
    # ==========================================================
    async def _restore_grid_if_needed(self, powerSession: PowerSession) -> None:
        """根据 MySQL 里存的 grid_meta 把电网对象恢复到内存，已有则跳过"""
        sid = powerSession.id
        if self.graph_service.has_grid_session(sid):
            return
        meta = powerSession.get_grid_meta() or {}
        grid_file = meta.get("last_grid_file")
        load_factor = float(meta.get("load_factor") or 1.0)
        # 优先恢复文件加载的真实电网
        if grid_file:
            try:
                print(f'尝试从文件恢复电网对象：{grid_file}')
                self._ensure_grid_loaded_from_file(sid, grid_file, load_factor)
            except Exception:
                pass  # 恢复失败就算了，用户再问时 LLM 会自己重新加载
            return
        grid_type = meta.get("last_grid_type")
        if grid_type and grid_type in _SUPPORTED_GRIDS:
            try:
                self._ensure_grid_loaded(sid, grid_type, load_factor)
            except Exception:
                pass  # 恢复失败就算了，用户再问时 LLM 会自己重建

    @staticmethod
    def _ensure_grid_loaded(session_id: str, grid_type: str, load_factor: float = 1.0) -> None:
        """创建该会话的电网对象（已存在则跳过），并按需调整负荷倍率"""
        gt_obj = get_grid_tools_obj(session_id)

        if getattr(gt_obj, "net", None) is None:
            # 还没有电网 → 创建，并打上 grid_type 补丁属性（GridTools 自己不记）
            try:
                result = gt_obj.create_test_grid(grid_type=grid_type)
                if result and result.get("success"):
                    setattr(gt_obj, "_patched_grid_type", grid_type)
            except Exception:
                return

        # 负荷倍率不是 1 才需要缩放
        try:
            factor = float(load_factor or 1.0)
            if abs(factor - 1.0) > 1e-6:
                gt_obj.set_load_scale(factor=factor)
        except Exception:
            pass  # 缩放失败不致命，用户下次说"负荷调到X倍"时 LLM 会再调

    @staticmethod
    def _ensure_grid_loaded_from_file(session_id: str, file_path: str,
                                      load_factor: float = 1.0) -> None:
        """从文件恢复真实电网对象（已存在则跳过），并按需调整负荷倍率"""
        gt_obj = get_grid_tools_obj(session_id)

        if getattr(gt_obj, "net", None) is None:
            try:
                result = gt_obj.load_grid_from_file(file_path=file_path)
                if result and result.get("success"):
                    setattr(gt_obj, "_patched_grid_file",
                            result.get("文件路径") or file_path)
            except Exception:
                return
        elif not getattr(gt_obj, "_patched_grid_file", None):
            setattr(gt_obj, "_patched_grid_file", file_path)

        try:
            factor = float(load_factor or 1.0)
            if abs(factor - 1.0) > 1e-6:
                gt_obj.set_load_scale(factor=factor)
        except Exception:
            pass