# -*- coding: utf-8 -*-
"""
会话管理接口：会话 CRUD + 电网重置
存储细节（MySQL / 内存降级）全部封装在 SessionService 里，
本文件只做路由编排和参数校验。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db_session
from schemas import SessionCreateRequest, SessionUpdateRequest, ok
from services import SessionService

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])


@router.post("")
async def create_session(
    req: SessionCreateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    result = await session_service.create_session(req)
    return ok(result, "会话创建成功")


@router.get("")
async def list_sessions(
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    data = await session_service.list_sessions(limit=limit)
    return ok(data)


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    detail = await session_service.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return ok(detail)


@router.patch("/{session_id}")
async def update_session(
    session_id: str,
    req: SessionUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    changed = await session_service.update_session(session_id, req)
    if not changed:
        raise HTTPException(status_code=404, detail="会话不存在或没有修改内容")
    return ok(None, "会话已更新")


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    ok_ = await session_service.delete_session(session_id)
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ok(None, "会话已删除")


@router.post("/{session_id}/reset")
async def reset_session_grid(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    session_service = SessionService(db)
    ok_ = await session_service.reset_grid(session_id)
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ok(None, "电网已重置")