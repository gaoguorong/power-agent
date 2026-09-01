# -*- coding: utf-8 -*-
"""
会话相关 DTO：创建/修改请求体、列表摘要、详情响应
"""
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """会话级配置（新建/修改时都可以传）"""
    default_grid_type: str = Field(
        default="case30",
        description="默认电网类型，当问题没提、也没上下文时用这个兜底",
    )
    ui_show_tool_details: bool = Field(
        default=True,
        description="AI回答里工具调用详情默认展开还是折叠",
    )
    ui_max_table_rows: int = Field(
        default=10, ge=1, le=200,
        description="数据表格最多显示多少行（超出折叠）",
    )
    ui_theme: str = Field(
        default="sgcc-green",
        description="UI主题：sgcc-green=国网绿，dark=深色",
    )


class SessionCreateRequest(BaseModel):
    """新建会话请求体"""
    name: str = Field(default="新会话", max_length=128, description="会话名称")
    config: Optional[SessionConfig] = Field(default=None, description="会话配置，不传用默认")


class SessionUpdateRequest(BaseModel):
    """修改会话请求体（传哪个字段改哪个，没传的不动）"""
    name: Optional[str] = Field(default=None, max_length=128, description="新名称")
    config: Optional[SessionConfig] = Field(default=None, description="新配置（全量覆盖）")


class SessionSummary(BaseModel):
    """会话列表里的一项（简洁格式）"""
    id: str
    name: str
    last_message: str = ""
    message_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    config: Dict[str, Any] = {}


class SessionDetailResponse(BaseModel):
    """单个会话详情（含消息历史）"""
    id: str
    name: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    config: Dict[str, Any] = {}
    messages: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="消息历史，按时间升序，每条含 role/content/tool_calls 等",
    )
