# -*- coding: utf-8 -*-
"""
核心：流式聊天接口（SSE）
"""
import traceback

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from models import get_db_session
from schemas import ChatRequest, json_dumps_safe, ok
from services import SessionService, GraphService

router = APIRouter(prefix="/api/sessions", tags=["聊天"])


@router.get("/{session_id}/chat/pending_interrupt")
async def get_pending_interrupt(session_id: str):
    """
    查询该会话是否有等待 resume 的 interrupt（人工审批）。
    前端刷新页面/切换会话后用它恢复审批面板，避免审批请求"丢"在 checkpoint 里。
    """
    graph = GraphService.get_instance()
    await graph.ensure_init()
    snapshot = await graph._compiled.aget_state(
        {"configurable": {"thread_id": session_id}})
    value = snapshot.interrupts[0].value if snapshot.interrupts else None
    return ok({"interrupt": value})


@router.post("/{session_id}/chat/resume")
async def chat_resume(
    session_id: str,
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    人工审批恢复：前端在收到 interrupt 事件后，用户点击"批准/拒绝"调这个接口。
    SSE 推送后续的执行结果。
    """
    async def event_generator():
        try:
            graph = GraphService.get_instance()
            async for ev in graph.chat_resume(session_id, req.question):
                if await request.is_disconnected():
                    return
                ev.setdefault("data", {})
                ev["data"]["session_id"] = session_id
                yield {"event": ev["event"], "data": json_dumps_safe(ev)}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json_dumps_safe({
                    "event": "error",
                    "data": {
                        "session_id": session_id,
                        "message": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=3),
                    },
                }),
            }

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.post("/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    🔥 核心接口：流式聊天
    用 Server-Sent Events (SSE) 推送事件：
      event=welcome    : 收到请求，开始处理
      event=tool_start : LLM 决定调用工具（前端显示"正在做xx"）
      event=tool_end   : 工具调用完成
      event=token      : LLM 正在输出回答文本（打字机效果）
      event=done       : 全部完成，附带完整结果
      event=error      : 出错了

    前端使用示例（JS）：
        const es = new EventSourcePOST(url, { body: JSON.stringify({question}) });
        es.onmessage = e => { console.log(JSON.parse(e.data)); };
    """
    # 先判断这个 session 存在不（避免前端随便传ID都能塞数据）
    # MySQL 查不到就查内存降级
    session_exists = False
    session_service = None
    try:
        session_service = SessionService(db)
        powerSession = await session_service.session_repo.get_by_id(session_id)
        if powerSession:
            session_exists = True
            # 顺便恢复电网对象（如果MySQL里有）
            try:
                await session_service._restore_grid_if_needed(powerSession)
            except Exception:
                pass
    except Exception as exc:
        print(f"[降级] chat_stream MySQL 查询失败：{exc}")

    # ------------------------------------------------------------
    # SSE 事件生成器：一边调用 GraphAgent，一边把事件推给前端
    # 聊天结束后还会写两个回数据库：电网元信息 + 消息数/最后预览
    # ------------------------------------------------------------
    async def event_generator():
        final_ai_text = ""
        graph = GraphService.get_instance()
        need_flush_db = False
        try:
            async for ev in graph.chat_stream(session_id, req.question):
                # 前端断开连接时立刻停（避免后端空跑）
                if await request.is_disconnected():
                    return

                ev_type = ev["event"]
                ev_data = ev["data"]

                # 每个事件包都加上 session_id，前端方便路由
                ev.setdefault("data", {})
                ev["data"]["session_id"] = session_id

                # 保存一下最终 AI 文本，聊天结束后写数据库
                if ev_type == "done":
                    final_ai_text = ev_data.get("ai_text", "") or ""
                    need_flush_db = True

                yield {"event": ev_type, "data": json_dumps_safe(ev)}

            # ---------- 聊天结束后把元信息刷回数据库 ----------
            if need_flush_db:
                # 先尝试 MySQL
                if session_service is not None:
                    try:
                        await session_service.update_grid_meta_to_db(session_id)
                    except Exception:
                        pass
                    try:
                        await session_service.update_last_message(session_id, final_ai_text, delta_count=2)
                    except Exception:
                        pass

        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json_dumps_safe({
                    "event": "error",
                    "data": {
                        "session_id": session_id,
                        "message": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=3),
                    },
                }),
            }

    return EventSourceResponse(event_generator(), media_type="text/event-stream")