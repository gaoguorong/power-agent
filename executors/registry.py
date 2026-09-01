# -*- coding: utf-8 -*-
"""
工具注册表（任务2.3）：工具的"户口本"

- register() 登记：重复 tool_id 直接报错，启动就能发现手滑
- get() 按 tool_id 查到定义和适配器
- execute() 统一执行入口：未注册的工具一律拒绝执行

第一版就用 Python 代码维护，不搞 YAML 配置。
LangChain 那边的 ALL_TOOLS 清单先不动，两套暂时并行。
"""
from pathlib import Path
from typing import Optional, Tuple

from pydantic import BaseModel, Field

from executors.base import ToolAdapter, ToolExecutionRequest
from executors.command_line import CommandLineAdapter
from executors.python_function import PythonFunctionAdapter
from schemas.tool_result import ToolError, ToolResult
from tools.langchain_tool import (run_ac_power_flow, set_load_scale,
                                  reset_grid_session)


class ToolDefinition(BaseModel):
    """一个工具的户口信息"""
    tool_id: str
    display_name: str
    description: str
    adapter_type: str          # python_function / command_line
    handler: str               # 给人看的处理入口描述，如 "tools.langchain_tool.run_ac_power_flow"
    timeout_seconds: int = 60
    read_only: bool = True     # 是否只读（会改电网的标 False，后面做重试/确认要用）
    input_schema: dict = Field(default_factory=dict)


class ToolRegistry:

    def __init__(self):
        # tool_id → (定义, 适配器)
        self._tools: dict = {}

    def register(self, definition: ToolDefinition, adapter: ToolAdapter) -> None:
        if definition.tool_id in self._tools:
            raise ValueError(f"工具ID重复: {definition.tool_id}")
        self._tools[definition.tool_id] = (definition, adapter)

    def get(self, tool_id: str) -> Optional[Tuple[ToolDefinition, ToolAdapter]]:
        return self._tools.get(tool_id)

    def tool_ids(self) -> list:
        return list(self._tools.keys())

    def execute(self, request: ToolExecutionRequest) -> dict:
        """统一执行入口：未注册 → 标准错误；已注册 → 交给对应适配器"""
        entry = self._tools.get(request.tool_id)
        if entry is None:
            return ToolResult(
                success=False,
                code="SYS_ERROR",
                message=f"未注册的工具 '{request.tool_id}'，禁止执行",
                error=ToolError(type="system", retryable=False),
            ).model_dump()

        _, adapter = entry
        try:
            adapter.validate(request)
        except ValueError as exc:
            return ToolResult(
                success=False,
                code="SYS_ERROR",
                message=str(exc),
                error=ToolError(type="system", retryable=False),
            ).model_dump()
        return adapter.execute(request)


def build_default_registry() -> ToolRegistry:
    """建好默认注册表：潮流、负荷倍率、重置会话 + 一个命令行测试工具

    三个现有工具直接复用 @tool 薄壳的 .invoke（它本身接收 dict 参数、
    内部已兜异常），一行计算逻辑都不用重写。
    """

    reg = ToolRegistry()

    reg.register(
        ToolDefinition(tool_id="run_ac_power_flow", display_name="交流潮流计算",
                       description="对当前会话电网执行交流潮流",
                       adapter_type="python_function",
                       handler="tools.langchain_tool.run_ac_power_flow",
                       read_only=True),
        PythonFunctionAdapter(run_ac_power_flow.invoke),
    )
    reg.register(
        ToolDefinition(tool_id="set_load_scale", display_name="负荷倍率",
                       description="按倍率缩放当前会话电网的全部负荷",
                       adapter_type="python_function",
                       handler="tools.langchain_tool.set_load_scale",
                       read_only=False),
        PythonFunctionAdapter(set_load_scale.invoke),
    )
    reg.register(
        ToolDefinition(tool_id="reset_grid_session", display_name="重置会话电网",
                       description="清空当前会话的电网计算状态",
                       adapter_type="python_function",
                       handler="tools.langchain_tool.reset_grid_session",
                       read_only=False),
        PythonFunctionAdapter(reset_grid_session.invoke),
    )

    # 命令行测试工具：独立脚本算两数之和
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo_cli_tool.py"
    reg.register(
        ToolDefinition(tool_id="demo_cli_add", display_name="命令行测试工具",
                       description="独立脚本：返回两个数之和",
                       adapter_type="command_line",
                       handler="scripts/demo_cli_tool.py",
                       timeout_seconds=10),
        CommandLineAdapter(script),
    )
    return reg
