# -*- coding: utf-8 -*-
"""
前端初始化配置项接口
"""
from fastapi import APIRouter

from config.model_config import LLM_CONFIG
from config.app_options import GRID_OPTIONS, QUICK_QUESTIONS
from schemas import AppOptionsResponse, QuickQuestion, SessionConfig, ok

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.get("/options")
async def get_config_options():
    """
    前端启动后第一个调的接口：
    拉取电网下拉框、快捷问题模板、默认配置、LLM可用性
    注意：必须用 ok() 包装，否则前端拦截器认不出响应格式，
    会把整个 AxiosResponse 当数据用（导致 llm_available 拿不到）
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
    return ok(AppOptionsResponse(
        grids=grids,
        quick_questions=quick_questions,
        default_config=SessionConfig(),
        llm_available=bool(LLM_CONFIG.get("api_key")),
    ))
