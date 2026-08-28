# -*- coding: utf-8 -*-
"""
FastAPI 服务主入口（组合根）
本文件只做装配：创建应用 → 中间件 → 启动钩子 → 注册路由 → 托管前端，
不包含任何具体接口实现（接口全部在 controllers/ 层）。

分层结构（类 MVC）：
    controllers/  C 层：HTTP 路由定义（只有 get/post 等接口编排）
    schemas/      DTO 层：请求/响应 Pydantic 模型
    services/     业务层：会话业务、GraphAgent 驱动、内存降级存储
    models/       M 层：MySQL 连接、ORM 模型、会话仓库
    agents/       Agent 层：LangGraph 状态机 + LLM 工厂
    tools/        独立工具函数（电网计算 @tool）
    config/       配置（环境变量、阈值、提示词、前端选项）

启动命令：
    开发模式：uvicorn main:app --reload --host 0.0.0.0 --port 8000
    生产模式：python main.py   （直接跑也行，文件底部有启动代码）

打开浏览器：
    Swagger API文档： http://localhost:8000/docs
    ReDoc 文档：      http://localhost:8000/redoc
"""
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------- 内部模块 ----------
from config.model_config import LLM_CONFIG, SERVER_CONFIG
from models import create_all_tables
from services import GraphService
from controllers import register_routers, mount_frontend

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
# 3. 注册路由（具体接口实现见 controllers/）
# ====================================================================
register_routers(app)

# SPA fallback 路由必须最后注册，所以前端托管放在所有 API 路由之后
mount_frontend(app)


# ====================================================================
# 4. 直接 `python main.py` 也能启动（不用记 uvicorn 命令）
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
