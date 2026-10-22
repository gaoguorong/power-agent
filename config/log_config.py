# -*- coding: utf-8 -*-
"""
统一日志配置：系统全部日志策略只看这一个文件。

日志清单：
    logs/app.log    应用运行日志（uvicorn、业务模块），控制台同步输出
    logs/llm_io.log LLM 每次调用的输入/输出轨迹（人读格式，单行一条）

使用方式：main.py 启动时调用一次 setup_logging()；
graph_agent 独立运行演示时在 __main__ 里自行调用。
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


# 【新增 2026-10-22】作用：集中装配全部日志（app.log/llm_io.log/httpx 降噪），
# 业务模块只通过 getLogger 取记录器，不感知文件路径与滚动策略。
def setup_logging():
    # 幂等保护：重复调用不重复挂载处理器，避免一条日志写多份
    if getattr(setup_logging, "_configured", False):
        return
    setup_logging._configured = True

    _LOG_DIR.mkdir(exist_ok=True)

    # httpx 请求日志降噪：只保留警告以上，正常请求不刷屏
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    # 应用日志：追加写 logs/app.log（超5MB滚动，保留2份备份），控制台同步输出
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s",
        handlers=[
            RotatingFileHandler(_LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    # LLM 轨迹日志：追加写 logs/llm_io.log（超2MB滚动，保留2份备份）；
    # 内容截断由 graph_agent 负责，这里只管落盘
    _llm_logger = logging.getLogger("llm_io")
    if not _llm_logger.handlers:
        _llm_handler = RotatingFileHandler(_LOG_DIR / "llm_io.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
        _llm_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _llm_logger.addHandler(_llm_handler)
        _llm_logger.setLevel(logging.INFO)
        _llm_logger.propagate = False  # 不向根记录器传播，避免同一条轨迹重复进 app.log
