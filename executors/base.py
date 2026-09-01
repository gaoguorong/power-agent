# -*- coding: utf-8 -*-
"""
脚本适配器基础接口（任务2.2）

目的：不管是普通 Python 函数，还是外部命令行脚本，都用同一种方式调用：
    adapter.validate(request)   → 参数检查
    adapter.execute(request)    → 返回标准 ToolResult 结构（dict）

以后新接一个成熟脚本：选/写一个适配器 + 到注册表登记一条，
Agent 核心代码（GraphService / GraphAgent）一行不用动。
"""
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class ToolExecutionRequest(BaseModel):
    """一次工具调用请求"""
    tool_id: str                                     # 要调哪个工具（必须已注册）
    case_revision_id: Optional[str] = None           # 算例版本（第三阶段才用，现在可空）
    parameters: dict = Field(default_factory=dict)   # 工具参数
    timeout_seconds: int = 60                        # 超时秒数，超时会强制终止


class ToolAdapter(ABC):
    """工具适配器：只负责"怎么跑"一类工具"""

    @abstractmethod
    def validate(self, request: ToolExecutionRequest) -> None:
        """参数检查，不合法就抛 ValueError"""

    @abstractmethod
    def execute(self, request: ToolExecutionRequest) -> dict:
        """执行工具，返回标准结构（ToolResult.model_dump() 的形状）"""
