# -*- coding: utf-8 -*-
"""
会话管理接口：会话 CRUD + 电网重置
带 MySQL 降级：MySQL 挂了就用 services.memory_store 的内存存储
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db_session
from schemas import SessionConfig, SessionCreateRequest, SessionUpdateRequest, ok
from services import SessionService, GraphService, memory_sessions

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])


@router.post("")
async def create_session(
    req: SessionCreateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """新建一个会话"""
    try:
        svc = SessionService(db)
        result = await svc.create_session(req)
        return ok(result, "会话创建成功")
    except Exception as exc:
        # MySQL 不可用时走内存降级
        cfg_dict = req.config.model_dump() if req.config else SessionConfig().model_dump()
        row = memory_sessions.create(req.name, cfg_dict)
        print(f"[降级] MySQL 不可用，使用内存存储创建会话：{exc}")
        return ok(row, "会话创建成功（降级模式，重启会丢失）")


@router.get("")
async def list_sessions(
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    """获取会话列表（侧边栏用），按最近使用排序"""
    try:
        svc = SessionService(db)
        data = await svc.list_sessions(limit=limit)
        # 如果 MySQL 里有数据就用 MySQL 的，否则合并内存里的
        if data:
            return ok(data)
    except Exception as exc:
        print(f"[降级] MySQL 不可用，读取内存会话列表：{exc}")
    # 兜底：返回内存中的
    return ok(memory_sessions.list(limit))


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取单个会话详情 + 完整消息历史（刷新页面时恢复聊天记录）"""
    # 先查 MySQL
    try:
        svc = SessionService(db)
        detail = await svc.get_session_detail(session_id)
        if detail:
            return ok(detail)
    except Exception as exc:
        print(f"[降级] get_session MySQL失败，查内存：{exc}")
    # 再查内存
    row = memory_sessions.get(session_id)
    if row is not None:
        graph = GraphService.get_instance()
        messages = await graph.get_session_messages(session_id)
        return ok({
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "config": row["config"],
            "messages": messages,
        })
    raise HTTPException(status_code=404, detail="会话不存在或已删除")


@router.patch("/{session_id}")
async def update_session(
    session_id: str,
    req: SessionUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """修改会话名称 或 会话配置"""
    changed = False
    try:
        svc = SessionService(db)
        changed = await svc.update_session(session_id, req)
    except Exception as exc:
        print(f"[降级] update_session MySQL失败，改内存：{exc}")
    # MySQL 没改成功，查内存
    if not changed and session_id in memory_sessions:
        changed = memory_sessions.update(
            session_id,
            name=req.name,
            config=req.config.model_dump() if req.config else None,
        )
    if not changed:
        raise HTTPException(status_code=404, detail="会话不存在或没有修改内容")
    return ok(None, "会话已更新")


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """删除会话（软删）"""
    ok_ = False
    try:
        svc = SessionService(db)
        ok_ = await svc.delete_session(session_id)
    except Exception as exc:
        print(f"[降级] delete_session MySQL失败，删内存：{exc}")
    if not ok_:
        ok_ = memory_sessions.delete(session_id)
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 无论如何清 GraphAgent 内存中的电网对象
    GraphService.get_instance().reset_grid_session(session_id)
    return ok(None, "会话已删除")


@router.post("/{session_id}/reset")
async def reset_session_grid(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """重置会话的电网状态（清空内存中的电网对象，对话历史保留）"""
    ok_ = False
    try:
        svc = SessionService(db)
        ok_ = await svc.reset_grid(session_id)
    except Exception as exc:
        print(f"[降级] reset_session MySQL失败，仅清内存：{exc}")
    # 无论如何都清内存中的电网对象
    GraphService.get_instance().reset_grid_session(session_id)
    if session_id in memory_sessions:
        memory_sessions.clear_preview(session_id)
        ok_ = True
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ok(None, "电网已重置")