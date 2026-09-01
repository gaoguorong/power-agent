# -*- coding: utf-8 -*-
"""
任务2.2/2.3 验收测试：适配器 + 注册表

覆盖验收标准：
- 简单 Python 函数走适配器成功
- 命令行测试脚本成功 / 超时终止 / 非零退出码
- 注册表：重复ID报错、未注册拒绝执行、必需工具已登记
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from executors import (CommandLineAdapter, PythonFunctionAdapter,
                       ToolExecutionRequest, build_default_registry)
from executors.registry import ToolDefinition, ToolRegistry
from schemas.tool_result import ToolResult
from tools import langchain_tool

STANDARD_KEYS = set(ToolResult.model_fields.keys())
DEMO_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "demo_cli_tool.py"


def _assert_standard(result: dict):
    assert set(result.keys()) == STANDARD_KEYS


# ---------------- 2.2 PythonFunctionAdapter ----------------

def test_python_function_adapter_ok():
    """简单 Python 函数：两数求和"""
    def add(params: dict):
        return {"success": True, "message": "ok", "sum": params["a"] + params["b"]}

    adapter = PythonFunctionAdapter(add)
    r = adapter.execute(ToolExecutionRequest(tool_id="add", parameters={"a": 1, "b": 2}))
    _assert_standard(r)
    assert r["success"] is True
    assert r["data"]["sum"] == 3


def test_python_function_adapter_exception():
    """函数抛异常 → 标准系统异常结构，不往外炸"""
    def boom(params: dict):
        raise RuntimeError("内部错误")

    adapter = PythonFunctionAdapter(boom)
    r = adapter.execute(ToolExecutionRequest(tool_id="boom"))
    _assert_standard(r)
    assert r["success"] is False
    assert r["code"] == "SYS_ERROR"


# ---------------- 2.2 CommandLineAdapter ----------------

def test_command_line_ok():
    """命令行脚本正常执行，stdout 的 JSON 被解析进标准结构"""
    adapter = CommandLineAdapter(DEMO_SCRIPT)
    r = adapter.execute(ToolExecutionRequest(
        tool_id="demo_cli_add", parameters={"a": 2, "b": 3}, timeout_seconds=15))
    _assert_standard(r)
    assert r["success"] is True
    assert r["data"]["sum"] == 5.0


def test_command_line_timeout():
    """超时能终止脚本，并返回标准失败结果（可重试）"""
    adapter = CommandLineAdapter(DEMO_SCRIPT)
    r = adapter.execute(ToolExecutionRequest(
        tool_id="demo_cli_add", parameters={"sleep": 3}, timeout_seconds=1))
    _assert_standard(r)
    assert r["success"] is False
    assert r["error"]["type"] == "timeout"
    assert r["error"]["retryable"] is True


def test_command_line_nonzero_exit():
    """非零退出码 → 标准错误，带上 stderr 便于排查"""
    adapter = CommandLineAdapter(DEMO_SCRIPT)
    r = adapter.execute(ToolExecutionRequest(
        tool_id="demo_cli_add", parameters={"fail": True}, timeout_seconds=15))
    _assert_standard(r)
    assert r["success"] is False
    assert "退出码" in r["message"]
    assert "模拟脚本执行失败" in r["error"]["details"]["stderr"]


# ---------------- 2.3 ToolRegistry ----------------

def test_registry_duplicate_raises():
    """重复 tool_id 在登记时就被发现"""
    reg = ToolRegistry()
    d = ToolDefinition(tool_id="x", display_name="x", description="x",
                       adapter_type="python_function", handler="x")
    reg.register(d, PythonFunctionAdapter(lambda p: {"success": True}))
    with pytest.raises(ValueError):
        reg.register(d, PythonFunctionAdapter(lambda p: {"success": True}))


def test_registry_unregistered_rejected():
    """未注册的工具不得执行，返回标准错误而不是抛异常"""
    reg = build_default_registry()
    r = reg.execute(ToolExecutionRequest(tool_id="no_such_tool"))
    _assert_standard(r)
    assert r["success"] is False
    assert "未注册" in r["message"]


def test_registry_required_tools():
    """验收要求的 4 个工具都登记在册"""
    reg = build_default_registry()
    ids = set(reg.tool_ids())
    assert {"run_ac_power_flow", "set_load_scale",
            "reset_grid_session", "demo_cli_add"} <= ids


def test_registry_dispatch_power_flow():
    """注册表能按 tool_id 找到适配器并真实执行：
    会话 t22 没建电网 → 潮流返回标准结构的业务失败（证明链路通）"""
    langchain_tool._sessions.pop("t22", None)
    try:
        reg = build_default_registry()
        r = reg.execute(ToolExecutionRequest(
            tool_id="run_ac_power_flow",
            parameters={"session_id": "t22"}))
        _assert_standard(r)
        assert r["success"] is False
        assert r["code"] == "BIZ_ERROR"
    finally:
        langchain_tool._sessions.pop("t22", None)


# ---------------- 主流程接入：GraphService._execute_tools ----------------

def test_graph_service_dispatch():
    """聊天主链路调度规则：注册优先 → 未登记回退老路 → 都没有算未知工具"""
    import json

    from services.graph_service import GraphService
    service = GraphService()  # 构造不发网络请求，只装配对象，安全离线构造
    langchain_tool._sessions.pop("t23", None)

    def _first(tool_calls):
        msgs = service._execute_tools(tool_calls)
        assert len(msgs) == 1
        return json.loads(msgs[0].content)

    try:
        # 1) 注册的外部脚本工具：接入前是"未知工具"，现在能真正执行（新能力）
        r = _first([{"name": "demo_cli_add", "id": "c1",
                     "args": {"a": 2, "b": 3}}])
        _assert_standard(r)
        assert r["success"] is True and r["data"]["sum"] == 5.0

        # 2) 注册的电网工具走适配器通道：未建电网算潮流 → 标准业务失败
        r = _first([{"name": "run_ac_power_flow", "id": "c2",
                     "args": {"session_id": "t23"}}])
        _assert_standard(r)
        assert r["success"] is False and r["code"] == "BIZ_ERROR"

        # 3) 未注册的工具（create_test_grid）回退老路，行为与接入前一致
        r = _first([{"name": "create_test_grid", "id": "c3",
                     "args": {"grid_type": "case9", "session_id": "t23"}}])
        _assert_standard(r)
        assert r["success"] is True and "grid_info" in r["data"]

        # 4) 注册表和 LangChain 清单都没有 → 未知工具标准错误
        r = _first([{"name": "no_such_tool", "id": "c4", "args": {}}])
        _assert_standard(r)
        assert r["success"] is False and "未知工具" in r["message"]
    finally:
        langchain_tool._sessions.pop("t23", None)
