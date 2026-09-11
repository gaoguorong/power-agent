# -*- coding: utf-8 -*-
"""
核心：流式聊天接口（SSE）
"""
import traceback

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from models import get_db_session
from schemas import ChatRequest, json_dumps_safe
from services import SessionService, GraphService, memory_sessions

router = APIRouter(prefix="/api/sessions", tags=["聊天"])


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
        row = await session_service.repo.get_by_id(session_id)
        if row:
            session_exists = True
            # 顺便恢复电网和消息历史（如果MySQL里有）
            try:
                await session_service._restore_grid_if_needed(row)
                await session_service.restore_messages_if_needed(row)
            except Exception:
                pass
    except Exception as exc:
        print(f"[降级] chat_stream MySQL 查询失败：{exc}")
    if not session_exists and session_id not in memory_sessions:
        raise HTTPException(status_code=404, detail="会话不存在，请先创建会话")

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
                    # 消息历史落库：重启后点历史会话还能看到聊天记录
                    try:
                        await session_service.persist_messages(session_id)
                    except Exception:
                        pass
                # 再更新内存（如果是降级模式）
                memory_sessions.touch(session_id, final_ai_text, delta_count=2)
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
