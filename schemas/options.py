# -*- coding: utf-8 -*-
"""
前端初始化配置项 DTO（下拉框、快捷问题、默认配置）
"""
from typing import List

from pydantic import BaseModel, Field

from .session import SessionConfig


class QuickQuestion(BaseModel):
    """快捷问题模板"""
    label: str = Field(description="按钮上显示的文字")
    example: str = Field(description="点击后填入输入框的完整问题")


class AppOptionsResponse(BaseModel):
    """前端初始化时拉取的各种选项"""

    class GridOption(BaseModel):
        value: str
        label: str
        desc: str

    grids: List[GridOption] = Field(description="可选电网类型列表")

    quick_questions: List[QuickQuestion] = Field(description="快捷问题模板列表")

    default_config: SessionConfig = Field(description="新建会话时的默认配置")

    llm_available: bool = Field(description="LLM是否已正确配置API Key")
