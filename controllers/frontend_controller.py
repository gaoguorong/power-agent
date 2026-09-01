# -*- coding: utf-8 -*-
"""
前端静态文件托管（Vue 3 SPA）
  build 产物：frontend/dist/*
  - /assets/* → 静态资源（js/css）
  - 其他所有路径（/、/session/xxx 等）→ 返回 SPA 的 index.html
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 项目根目录下的前端构建产物
_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def mount_frontend(app: FastAPI) -> None:
    """把前端 SPA 挂到 app 上（必须在所有 /api 路由注册完之后调用，
    否则 SPA fallback 会拦截 /docs、/openapi.json 等）"""
    if not (_FRONTEND_DIST.exists() and (_FRONTEND_DIST / "index.html").exists()):
        return

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
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        # 先尝试当作真实文件返回（assets下的文件走上面mount的路由，这里只会命中 dist 根目录里的其他文件）
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file() and str(candidate.resolve()).startswith(str(_FRONTEND_DIST.resolve())):
            return FileResponse(str(candidate))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
