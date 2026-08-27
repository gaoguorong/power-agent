# -*- coding: utf-8 -*-
"""
FastAPI 服务主入口
启动命令：
    开发模式：uvicorn main:app --reload --host 0.0.0.0 --port 8000
    生产模式：python main.py   （直接跑也行，文件底部有启动代码）

打开浏览器：
    Swagger API文档： http://localhost:8000/docs
    ReDoc 文档：      http://localhost:8000/redoc
"""
import asyncio
from typing import Any, Dict, Optional

import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import text
from db.mysql import engine

# ---------- 内部模块 ----------
from config.ts_config import LLM_CONFIG, SERVER_CONFIG
from config.app_options import GRID_OPTIONS, QUICK_QUESTIONS
from db.mysql import create_all_tables, get_db_session
from schemas import (
    SessionConfig,
    SessionCreateRequest,
    SessionUpdateRequest,
    SessionSummary,
    SessionDetailResponse,
    ChatRequest,
    AppOptionsResponse,
    QuickQuestion,
    ok,
    fail,
)
from services import SessionService, GraphService

# ====================================================================
# 1. 创建 FastAPI 应用
# ====================================================================
app = FastAPI(
    title="⚡ 电网分析智能体 API",
    description="基于 LangGraph + pandapower 的电力系统自然语言分析平台",
    version="1.0.0",
)

# ---------- CORS 跨域 ----------
# 前后端分离场景（比如前端跑在 Vite 5173）必须加这个
app.add_middleware(
    CORSMiddleware,
    allow_origins=SERVER_CONFIG["cors_origins"] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================
# 2. 启动时做的事：建表 + 预热 GraphAgent（避免第一次请求很慢）
# ====================================================================
@app.on_event("startup")
async def on_startup():
    """服务启动时执行一次"""
    print("=" * 60)
    print("🚀 正在启动电网分析智能体服务...")

    # --- 2.1 自动建 MySQL 表（如果还没建） ---
    try:
        await create_all_tables()
        print("✅ MySQL 会话表已就绪")
    except Exception as exc:
        print(f"⚠️  MySQL 初始化失败：{exc}")
        print("   请检查 .env 里的 MYSQL_URL 是否正确，MySQL 服务是否启动")

    # --- 2.2 预热 GraphAgent（加载 LLM + 工具，第一次比较慢） ---
    try:
        GraphService.get_instance()
        print("✅ GraphAgent 已就绪（消息历史存进程内存）")
    except Exception as exc:
        import traceback
        print(f"⚠️  GraphAgent 初始化失败：{exc}")
        traceback.print_exc(limit=4)

    # --- 2.3 检查 LLM API Key 有没有填 ---
    if not LLM_CONFIG.get("api_key"):
        print("⚠️  警告：未设置 LLM_API_KEY 环境变量，LLM 功能将不可用")
    else:
        print(f"✅ LLM 已配置：模型={LLM_CONFIG.get('model')}")

    print(f"🌐 服务地址：http://{SERVER_CONFIG['host']}:{SERVER_CONFIG['port']}")
    print(f"📖 Swagger文档：http://localhost:{SERVER_CONFIG['port']}/docs")
    print("=" * 60)


# ====================================================================
# 3. 健康检查
# ====================================================================
@app.get("/api/health", tags=["系统"])
async def health_check():
    """服务健康检查（前端/监控用）"""
    data: Dict[str, Any] = {
        "status": "ok",
        "llm_available": bool(LLM_CONFIG.get("api_key")),
        "llm_model": LLM_CONFIG.get("model"),
    }
    # 顺手测一下 MySQL 通不通
    try:

        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        data["mysql_available"] = True
    except Exception as exc:
        data["mysql_available"] = False
        data["mysql_error"] = str(exc)
    return ok(data)


# ====================================================================
# 4. 前端初始化配置项（电网下拉框、快捷问题、默认配置）
# ====================================================================
@app.get("/api/config/options", tags=["配置"], response_model=AppOptionsResponse)
async def get_config_options():
    """
    前端启动后第一个调的接口：
    拉取电网下拉框、快捷问题模板、默认配置、LLM可用性
    """
    grids = [
        AppOptionsResponse.GridOption(
            value=g["value"], label=g["label"], desc=g["desc"]
        )
        for g in GRID_OPTIONS
    ]
    quick_questions = [
        QuickQuestion(label=q["label"], example=q["example"])
        for q in QUICK_QUESTIONS
    ]
    return AppOptionsResponse(
        grids=grids,
        quick_questions=quick_questions,
        default_config=SessionConfig(),
        llm_available=bool(LLM_CONFIG.get("api_key")),
    )


# ====================================================================
# 简易内存降级存储：当 MySQL 不可用时使用（保证前端至少能试用）
# ====================================================================
import uuid as _uuid
from datetime import datetime
_MEM_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _mem_make_session(name: str, config: Optional[Dict] = None) -> Dict[str, Any]:
    sid = _uuid.uuid4().hex
    now = datetime.now().isoformat()
    cfg = config or SessionConfig().model_dump()
    row = {
        "id": sid,
        "name": name or "新会话",
        "last_message": "",
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
        "config": cfg,
    }
    _MEM_SESSIONS[sid] = row
    return row


# ====================================================================
# 5. 会话 CRUD 接口（带 MySQL 降级：MySQL 挂了就用内存）
# ====================================================================

@app.post("/api/sessions", tags=["会话管理"])
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
        row = _mem_make_session(req.name, cfg_dict)
        print(f"[降级] MySQL 不可用，使用内存存储创建会话：{exc}")
        return ok(row, "会话创建成功（降级模式，重启会丢失）")


@app.get("/api/sessions", tags=["会话管理"])
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
    mem_list = sorted(
        list(_MEM_SESSIONS.values()),
        key=lambda x: x.get("updated_at", ""),
        reverse=True,
    )[:limit]
    return ok(mem_list)


@app.get("/api/sessions/{session_id}", tags=["会话管理"])
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
    if session_id in _MEM_SESSIONS:
        row = _MEM_SESSIONS[session_id]
        graph = GraphService.get_instance()
        messages = graph.get_session_messages(session_id)
        return ok({
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "config": row["config"],
            "messages": messages,
        })
    raise HTTPException(status_code=404, detail="会话不存在或已删除")


@app.patch("/api/sessions/{session_id}", tags=["会话管理"])
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
    if not changed and session_id in _MEM_SESSIONS:
        if req.name is not None:
            _MEM_SESSIONS[session_id]["name"] = req.name
            _MEM_SESSIONS[session_id]["updated_at"] = datetime.now().isoformat()
            changed = True
        if req.config is not None:
            _MEM_SESSIONS[session_id]["config"] = req.config.model_dump()
            _MEM_SESSIONS[session_id]["updated_at"] = datetime.now().isoformat()
            changed = True
    if not changed:
        raise HTTPException(status_code=404, detail="会话不存在或没有修改内容")
    return ok(None, "会话已更新")


@app.delete("/api/sessions/{session_id}", tags=["会话管理"])
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
        if session_id in _MEM_SESSIONS:
            del _MEM_SESSIONS[session_id]
            ok_ = True
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 无论如何清 GraphAgent 内存中的电网对象
    GraphService.get_instance().reset_grid_session(session_id)
    return ok(None, "会话已删除")


@app.post("/api/sessions/{session_id}/reset", tags=["会话管理"])
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
    if session_id in _MEM_SESSIONS:
        _MEM_SESSIONS[session_id]["last_message"] = ""
        _MEM_SESSIONS[session_id]["updated_at"] = datetime.now().isoformat()
        ok_ = True
    if not ok_:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ok(None, "电网已重置")


# ====================================================================
# 6. 核心：流式聊天接口（SSE）
# ====================================================================

@app.post("/api/sessions/{session_id}/chat/stream", tags=["聊天"])
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
    svc = None
    try:
        svc = SessionService(db)
        row = await svc.repo.get_by_id(session_id)
        if row:
            session_exists = True
            # 顺便恢复电网（如果MySQL里有元数据）
            try:
                await svc._restore_grid_if_needed(row)
            except Exception:
                pass
    except Exception as exc:
        print(f"[降级] chat_stream MySQL 查询失败：{exc}")
    if not session_exists and session_id not in _MEM_SESSIONS:
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

                # 推给前端（SSE 标准格式：event: xxx\ndata: <JSON字符串>\n\n）
                # ⚠️  注意1：这里的 JSON 就是 ev 本身（单层结构）。
                #         之前错误地把 ev 整体包进外层 data 字段，导致前端 JSON.parse 之后多了一层嵌套，
                #         前端拿不到 .data.text / .data.name 等字段 → 聊天区什么都不渲染。
                # ⚠️  注意2：EventSourceResponse 接收的是 {"event": <SSE事件名>, "data": <字符串或可序列化对象>}
                #         字符串不会被二次序列化，所以这里传 _json_dumps_safe(ev) 正好。
                yield {"event": ev_type, "data": _json_dumps_safe(ev)}

            # ---------- 聊天结束后把元信息刷回数据库 ----------
            if need_flush_db:
                # 先尝试 MySQL
                if svc is not None:
                    try:
                        await svc.update_grid_meta_to_db(session_id)
                    except Exception:
                        pass
                    try:
                        await svc.update_last_message(session_id, final_ai_text, delta_count=2)
                    except Exception:
                        pass
                # 再更新内存（如果是降级模式）
                if session_id in _MEM_SESSIONS:
                    _MEM_SESSIONS[session_id]["last_message"] = final_ai_text[:500]
                    _MEM_SESSIONS[session_id]["message_count"] += 2
                    _MEM_SESSIONS[session_id]["updated_at"] = datetime.now().isoformat()
        except Exception as exc:  # noqa: BLE001
            import traceback
            yield {
                "event": "error",
                "data": _json_dumps_safe({
                    "event": "error",
                    "data": {
                        "session_id": session_id,
                        "message": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=3),
                    },
                }),
            }

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


# ====================================================================
# 7. 小工具函数
# ====================================================================

def _json_dumps_safe(obj: Any) -> str:
    """安全的 json.dumps（遇到奇怪的类型不会炸）"""
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


# ====================================================================
# 7.5 前端静态文件（Vue 3 SPA）
#   build 产物：frontend/dist/*
#   - /assets/* → 静态资源（js/css）
#   - 其他所有路径（/、/session/xxx 等）→ 返回 SPA 的 index.html
# ====================================================================

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

if _FRONTEND_DIST.exists() and (_FRONTEND_DIST / "index.html").exists():
    # 单独把 /assets 挂成静态目录（因为里面文件名有内容哈希，不会和其他路径冲突）
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend_assets")

    # /favicon.svg 单独处理
    if (_FRONTEND_DIST / "favicon.svg").exists():
        @app.get("/favicon.svg", include_in_schema=False)
        async def favicon_svg():
            return FileResponse(str(_FRONTEND_DIST / "favicon.svg"))

    @app.get("/", include_in_schema=False)
    async def spa_index():
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    # SPA fallback：所有非 /api 开头、也不是已有静态文件的 GET，都返回 index.html
    # （这个路由必须放在最后注册，否则会拦截 /docs /openapi.json 等）
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        # 先尝试当作真实文件返回（assets下的文件走上面mount的路由，这里只会命中 dist 根目录里的其他文件）
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file() and str(candidate.resolve()).startswith(str(_FRONTEND_DIST.resolve())):
            return FileResponse(str(candidate))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))


# ====================================================================
# 8. 直接 `python main.py` 也能启动（不用记 uvicorn 命令）
# ====================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=SERVER_CONFIG["host"],
        port=SERVER_CONFIG["port"],
        reload=False,    # 生产环境关掉 reload
        log_level="info",
    )