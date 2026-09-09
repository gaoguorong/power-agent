# -*- coding: utf-8 -*-
"""
MySQL 数据库连接初始化
用 SQLAlchemy 做 ORM，异步连接（aiomysql）
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config.model_config import DATABASE_CONFIG

# ========== 1. 创建异步引擎 ==========
# 说明：pool_pre_ping=True 会在获取连接前先ping一下，避免拿到断开的连接
engine = create_async_engine(
    DATABASE_CONFIG["mysql_url"],
    echo=False,              # True会打印所有SQL，调试时打开
    pool_pre_ping=True,      # 自动检测失效连接
    pool_size=10,            # 连接池大小
    max_overflow=20,         # 连接池满了最多再开多少
    pool_recycle=3600,       # 1小时自动回收连接（避免MySQL 8小时断开）
)

# ========== 2. 异步会话工厂 ==========
# expire_on_commit=False 让 session commit 之后对象还能继续用
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ========== 3. 所有 ORM 模型的基类 ==========
class Base(DeclarativeBase):
    """所有表模型都继承这个类"""
    pass


# ========== 4. FastAPI 用的依赖：每次请求给一个独立的 DB Session ==========
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends 用。
    使用方法：
        async def xxx(db: AsyncSession = Depends(get_db_session)):
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            if session.is_active:
                await session.rollback()
            raise
        else:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# ========== 5. 建表工具：服务启动时调用一次 ==========
async def create_all_tables():
    """
    自动创建所有继承了 Base 的表（如果还不存在）。
    注意：生产环境建议用 Alembic 做迁移，这里仅开发阶段用。
    """
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)  # 调试清空表时用
        await conn.run_sync(Base.metadata.create_all)