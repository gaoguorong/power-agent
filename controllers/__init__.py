# -*- coding: utf-8 -*-
"""
C 层：HTTP 路由层（Controller）
每个 controller 负责一组接口，只包含路由定义与请求/响应编排：
- config_controller   ：前端初始化配置项（/api/config/*）
- session_controller  ：会话 CRUD + 电网重置（/api/sessions/*）
- chat_controller     ：SSE 流式聊天（/api/sessions/{id}/chat/stream）
- frontend_controller ：前端 SPA 静态文件托管

业务逻辑一律下沉到 services 层，数据访问走 models 层。
"""
from fastapi import FastAPI

from .config_controller import router as config_router
from .session_controller import router as session_router
from .chat_controller import router as chat_router
from .frontend_controller import mount_frontend


def register_routers(app: FastAPI) -> None:
    """把所有 API 路由挂到 app 上（在 main.py 中调用）"""
    app.include_router(config_router)
    app.include_router(session_router)
    app.include_router(chat_router)


__all__ = ["register_routers", "mount_frontend"]
