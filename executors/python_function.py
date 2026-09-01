# -*- coding: utf-8 -*-
"""
PythonFunctionAdapter：调用普通 Python 函数（包括现有 @tool 的 .invoke）

func 约定：接收一个 dict 参数，返回 dict（或直接抛异常）。
异常不用自己接，execute 里统一交给 normalize 翻译成标准结构。
"""
from typing import Callable

from executors.base import ToolAdapter, ToolExecutionRequest
from schemas.tool_result import normalize_tool_result


class PythonFunctionAdapter(ToolAdapter):

    def __init__(self, func: Callable[[dict], object]):
        self.func = func

    def validate(self, request: ToolExecutionRequest) -> None:
        if not callable(self.func):
            raise ValueError("PythonFunctionAdapter 的 func 必须是可调用对象")

    def execute(self, request: ToolExecutionRequest) -> dict:
        try:
            raw = self.func(request.parameters)
        except Exception as exc:
            raw = exc  # 异常交给 normalize 统一翻译成系统异常
        return normalize_tool_result(raw, request.tool_id)
