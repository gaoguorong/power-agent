# -*- coding: utf-8 -*-
"""executors 包（任务2.2 + 2.3）：统一工具/脚本接入层"""
from .base import ToolAdapter, ToolExecutionRequest
from .python_function import PythonFunctionAdapter
from .command_line import CommandLineAdapter
from .registry import (ToolDefinition, ToolRegistry, build_default_registry)

__all__ = [
    "ToolAdapter",
    "ToolExecutionRequest",
    "PythonFunctionAdapter",
    "CommandLineAdapter",
    "ToolDefinition",
    "ToolRegistry",
    "build_default_registry",
]
