# -*- coding: utf-8 -*-
"""
聊天相关 DTO
"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """发送聊天消息请求体"""
    question: str = Field(..., min_length=1, max_length=5000, description="用户问题文本")
