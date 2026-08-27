# -*- coding: utf-8 -*-
"""
Pydantic 数据模型（请求/响应参数校验）
作用：
1. 自动校验前端传来的参数（类型、必填、长度等）
2. 给 FastAPI 的 Swagger 文档自动生成说明
3. 让接口代码拿到的一定是干净合法的数据
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field

# ============================================================
# 1. 会话相关
# ============================================================

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


# ============================================================
# 2. 聊天相关
# ============================================================

class ChatRequest(BaseModel):
    """发送聊天消息请求体"""
    question: str = Field(..., min_length=1, max_length=5000, description="用户问题文本")


# ============================================================
# 3. 前端初始化配置项（下拉框、默认值这些）
# ============================================================

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


# ============================================================
# 4. 通用响应包装（尽量统一格式）
# ============================================================

class ApiResponse(BaseModel):
    """所有普通接口的统一返回格式"""
    code: int = Field(default=0, description="0=成功，其他=错误码")
    message: str = Field(default="success", description="错误说明或成功提示")
    data: Optional[Any] = Field(default=None, description="业务数据")


# 下面这个是给工具函数用的：快速构造成功/失败响应
def ok(data: Any = None, message: str = "success") -> Dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 400, data: Any = None) -> Dict[str, Any]:
    return {"code": code, "message": message, "data": data}