# -*- coding: utf-8 -*-
"""
DTO 层：Pydantic 请求/响应模型
作用：
1. 自动校验前端传来的参数（类型、必填、长度等）
2. 给 FastAPI 的 Swagger 文档自动生成说明
3. 让接口代码拿到的一定是干净合法的数据

按域拆分：
- common   ：通用响应包装（ApiResponse / ok / fail）+ 序列化工具
- session  ：会话相关（创建/修改/列表/详情）
- chat     ：聊天相关
- options  ：前端初始化配置项（下拉框、快捷问题）
"""
from .common import ApiResponse, ok, fail, json_dumps_safe
from .session import (
    SessionConfig,
    SessionCreateRequest,
    SessionUpdateRequest,
    SessionSummary,
    SessionDetailResponse,
)
from .chat import ChatRequest
from .options import QuickQuestion, AppOptionsResponse
from .tool_result import ToolError, ToolResult, normalize_tool_result

__all__ = [
    "ApiResponse",
    "ok",
    "fail",
    "json_dumps_safe",
    "SessionConfig",
    "SessionCreateRequest",
    "SessionUpdateRequest",
    "SessionSummary",
    "SessionDetailResponse",
    "ChatRequest",
    "QuickQuestion",
    "AppOptionsResponse",
    "ToolError",
    "ToolResult",
    "normalize_tool_result",
]
