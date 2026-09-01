# -*- coding: utf-8 -*-
"""
任务2.1 工具结果合同测试

验收点：成功 / 业务失败 / 系统异常 三种结果结构完全一致，且都能 JSON 序列化。
不调用真实LLM、不依赖MySQL，只用 pandapower 本地计算。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from schemas.tool_result import ToolResult, normalize_tool_result
from tools import langchain_tool
from tools.langchain_tool import create_test_grid, run_ac_power_flow, set_load_scale

# 三种结果必须包含的字段（与 ToolResult 一致）
STANDARD_KEYS = set(ToolResult.model_fields.keys())


@pytest.fixture(autouse=True)
def _clean_session():
    """每个用例前后清掉测试会话的电网对象，互不干扰"""
    langchain_tool._sessions.pop("t21", None)
    yield
    langchain_tool._sessions.pop("t21", None)


def _assert_standard(result: dict):
    """合同检查：字段齐全 + 可 JSON 序列化（SSE/ToolMessage 都靠它）"""
    assert set(result.keys()) == STANDARD_KEYS
    json.dumps(result, ensure_ascii=False, default=str)


def test_success_result():
    """成功：建网 + 潮流收敛"""
    r1 = create_test_grid.invoke({"grid_type": "case9", "session_id": "t21"})
    n1 = normalize_tool_result(r1, "create_test_grid")
    _assert_standard(n1)
    assert n1["success"] is True
    assert n1["code"] == "OK"
    assert n1["error"] is None
    # 旧字段原样保留在 data 里，前端现有解析不受影响
    assert n1["data"]["success"] is True
    assert "grid_info" in n1["data"]

    r2 = run_ac_power_flow.invoke({"session_id": "t21"})
    n2 = normalize_tool_result(r2, "run_ac_power_flow")
    _assert_standard(n2)
    assert n2["success"] is True
    assert n2["code"] == "OK"


def test_business_failure_result():
    """业务失败：电网还没创建就算潮流，工具明确报"请先创建电网模型"（不重试）"""
    r = run_ac_power_flow.invoke({"session_id": "t21"})
    n = normalize_tool_result(r, "run_ac_power_flow")
    _assert_standard(n)
    assert n["success"] is False
    assert n["code"] == "BIZ_ERROR"
    assert n["error"]["type"] == "business"
    assert n["error"]["retryable"] is False
    assert "请先创建电网模型" in n["message"]


def test_system_exception_result():
    """系统异常：工具没接住的异常，传到出口后也能变成标准结构"""
    n = normalize_tool_result(ZeroDivisionError("boom"), "fake_tool")
    _assert_standard(n)
    assert n["success"] is False
    assert n["code"] == "SYS_ERROR"
    assert n["error"]["type"] == "system"
    assert "ZeroDivisionError" in n["message"]

    # 非 dict 的乱返回也归入系统异常
    n2 = normalize_tool_result(None, "fake_tool")
    _assert_standard(n2)
    assert n2["code"] == "SYS_ERROR"


def test_real_exception_caught_by_wrapper():
    """真实异常路径：非法负荷倍率会让 GridTools 抛异常，
    旧薄壳把它接住返回 success=False，出口翻译后仍是标准结构（不炸）"""
    create_test_grid.invoke({"grid_type": "case9", "session_id": "t21"})
    r = set_load_scale.invoke({"factor": -1.0, "session_id": "t21"})
    n = normalize_tool_result(r, "set_load_scale")
    _assert_standard(n)
    assert n["success"] is False


def test_all_shapes_identical():
    """三种结果的字段集合必须完全一致（验收标准：成功和失败结构一致）"""
    ok = normalize_tool_result({"success": True, "message": "好"}, "t")
    biz = normalize_tool_result({"success": False, "message": "不收敛"}, "t")
    syserr = normalize_tool_result(RuntimeError("x"), "t")
    assert set(ok.keys()) == set(biz.keys()) == set(syserr.keys()) == STANDARD_KEYS
