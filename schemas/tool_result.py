# -*- coding: utf-8 -*-
"""
标准工具结果（任务2.1）

作用：所有工具的执行结果，在"正式出口"统一转成同一种形状，
不管成功还是失败，字段都一样，前端/LLM/后续重试逻辑都认这个结构。

旧工具（grid_tools / langchain_tool）内部返回值一行不动，
只在出口处调 normalize_tool_result() 做一次"翻译"。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    """失败信息：区分"业务算不出来"和"系统出故障"，为后续重试策略留依据"""
    type: str                     # business=业务失败(潮流不收敛等，不重试) / system=系统异常(可重试)
    retryable: bool = False       # 是否允许重试
    details: Dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """统一工具结果：成功和失败都长这样"""
    success: bool
    code: str                     # OK / BIZ_ERROR / SYS_ERROR
    message: str                  # 给LLM和用户看的一句话
    summary: Dict = Field(default_factory=dict)    # 关键指标摘要
    data: Optional[Any] = None    # 完整业务数据（旧工具返回的原始字段放这里）
    artifacts: List = Field(default_factory=list)  # 附件（图表/文件路径），当前留空
    error: Optional[ToolError] = None


def normalize_tool_result(raw_result: Any, tool_name: str) -> dict:
    """把工具的原始返回值翻译成标准结构（普通dict，可直接 json.dumps）。

    三种输入：
    1. dict 且 success=True  → 成功，原始字段原样放进 data
    2. dict 且 success=False → 业务失败（工具自己明确报的错）
    3. 异常对象 / None / 其他 → 系统异常（工具没接住的错）
    """
    # ---- 情况3：系统异常 ----
    if isinstance(raw_result, BaseException):
        exc = raw_result
        return ToolResult(
            success=False,
            code="SYS_ERROR",
            message=f"工具 {tool_name} 执行异常: {type(exc).__name__}: {exc}",
            error=ToolError(type="system", retryable=False,
                            details={"exception": type(exc).__name__}),
        ).model_dump()

    if not isinstance(raw_result, dict):
        return ToolResult(
            success=False,
            code="SYS_ERROR",
            message=f"工具 {tool_name} 返回了无法识别的结果类型: {type(raw_result).__name__}",
            error=ToolError(type="system", retryable=False),
        ).model_dump()
    
    success = bool(raw_result.get("success", True))
    message = str(raw_result.get("message") or "")
    
    # ---- 情况1：成功 ----
    if success:
        return ToolResult(
            success=True,
            code="OK",
            message=message or f"{tool_name} 执行成功",
            data=raw_result,   # 旧结构原样保留，兼容前端现有解析
        ).model_dump()
    
    # ---- 情况2：业务失败 ----
    return ToolResult(
        success=False,
        code="BIZ_ERROR",
        message=message or f"{tool_name} 执行失败",
        data=raw_result,
        error=ToolError(type="business", retryable=False),
    ).model_dump()