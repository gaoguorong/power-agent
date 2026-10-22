# -*- coding: utf-8 -*-
"""
LASCH 前瞻调度系统工具模块

封装对 LASCH_GS_STANDALONE 后台 HTTP API 的调用。
LASCH 需提前启动: python run_backend.py --optimizer-mode highs
默认地址 http://127.0.0.1:18080，可通过环境变量 LASCH_API_BASE 覆盖。
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional
from langchain_core.tools import tool

LASCH_BASE = os.environ.get("LASCH_API_BASE", "http://127.0.0.1:18080")
LASCH_TOKEN = os.environ.get("LASCH_API_TOKEN", "")


def _http(method: str, path: str, body=None, timeout: int = 10):
    url = f"{LASCH_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if LASCH_TOKEN:
        headers["Authorization"] = f"Bearer {LASCH_TOKEN}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
        except Exception:
            detail = {"detail": str(e)}
        return e.code, detail
    except Exception as e:
        return None, {"detail": str(e)}


@tool
def lasch_health_check(session_id: str = "default") -> Dict:
    """
    检查 LASCH 前瞻调度后台是否可用。
    【触发条件】任何需要调用前瞻调度的任务前，先调本工具确认后台活着。
    【返回】success=true 表示 LASCH 可用；success=false 时把 error 直接告诉用户。
    """
    status, data = _http("GET", "/health", timeout=5)
    if status == 200:
        return {"success": True, "message": "LASCH 前瞻调度后台可用", "data": data}
    return {"success": False, "message": f"LASCH 后台不可用（HTTP {status}）", "error": data}


@tool
def lasch_submit_workflow(
    time_window_start: str,
    time_window_end: str,
    scenario_count: int = 3,
    mode: str = "scenario_then_optimize",
    step_min: int = 15,
    task_name: str = "Power Agent 前瞻调度分析",
    solver_time_limit_sec: int = 300,
    trade_time: str = None,
    focus_results: Optional[str] = None,
    session_id: str = "default",
) -> Dict:
    """
    提交 LASCH 前瞻调度工作流（场景生成 + SCUC 优化）。
    【触发条件】用户输入包含"前瞻调度"关键词时调用本工具。
    【必填】time_window_start / time_window_end —— 分析时间窗口，格式 "2025-10-03 12:00:00"。
            如果用户没给明确的时间窗口，必须反问，不要瞎填。
    【参数】
        time_window_start: 分析窗口开始时间，如 "2025-10-03 12:00:00"
        time_window_end:   分析窗口结束时间，如 "2025-10-03 16:00:00"
        scenario_count:    生成场景数（默认3，本机内存有限建议≤3）
        mode:              scenario_only(只生成场景) / optimize_baseline(只优化基线) /
                           scenario_then_optimize(场景生成+优化全流程，默认)
        step_min:          时间步长（分钟），默认15
        task_name:         任务名称（给用户看的标签）
        solver_time_limit_sec: HiGHS 求解时间上限，默认300秒（HiGHS 比 COPT 慢很多）
        trade_time:        交易时间（可选，默认用 time_window_start）
        focus_results:     重点关注结果，JSON 数组字符串，如 '["reserve"]' 或 '["reserve","section_flow"]'
                           不需要就直接不传该参数
    【返回】
        成功: {"success": true, "workflow_id": "wf_xxx", ...} —— 记下来等下查状态
        失败: {"success": false, "message": "...", "error": ...}
    """
    requirement: Dict = {
        "task_type": "前瞻调度",
        "task_name": task_name,
        "time_window": {
            "start": time_window_start,
            "end": time_window_end,
            "step_min": step_min,
        },
    }
    if trade_time:
        requirement["trade_time"] = trade_time
    focus_list = None
    if focus_results:
        try:
            parsed = json.loads(focus_results) if isinstance(focus_results, str) else focus_results
            if isinstance(parsed, list) and parsed:
                focus_list = parsed
        except (json.JSONDecodeError, TypeError):
            focus_list = None
    if focus_list:
        requirement["analysis_focus"] = [
            {"object_type": "system", "object_name": "system", "attribute": f}
            if isinstance(f, str)
            else f
            for f in focus_list
        ]

    body: Dict = {
        "mode": mode,
        "requirement": requirement,
        "scenario_control": {"scenario_count": scenario_count, "seed": 20},
    }
    status, data = _http("POST", "/api/v1/workflows", body=body)
    if status == 202:
        return {
            "success": True,
            "message": "前瞻调度任务已提交，正在后台执行",
            "workflow_id": data.get("workflow_id"),
            "submission_id": data.get("submission_id"),
            "mode": mode,
            "scenario_count": scenario_count,
            "time_window": f"{time_window_start} ~ {time_window_end}",
        }
    return {
        "success": False,
        "message": f"提交前瞻调度任务失败",
        "http_status": status,
        "error": data,
    }


@tool
def lasch_wait_workflow(
    workflow_id: str,
    max_wait_sec: int = 600,
    poll_interval_sec: int = 5,
    session_id: str = "default",
) -> Dict:
    """
    阻塞等待 LASCH 前瞻调度工作流完成（代码层轮询，不会消耗 LLM token）。
    【使用时机】lasch_submit_workflow 返回 workflow_id 后，立刻调本工具等结果。
    【不要】手动循环调 lasch_query_status 来等待——那会反复消耗 LLM token，效率低还容易被截断。
    【参数】
        workflow_id:  submit 返回的 workflow_id
        max_wait_sec: 最长等待秒数，默认600（10分钟，HiGHS 比较慢）
        poll_interval_sec: 轮询间隔，默认5秒
    【返回】
        成功: {"success": true, "final_status": "succeeded", "wait_sec": 123.4, ...}
        失败: {"success": false, "final_status": "...", "message": "...", "wait_sec": ...}
        超时: {"success": false, "final_status": "timeout", "message": "...", "wait_sec": ...}
    """
    terminal_statuses = {"succeeded", "failed", "cancelled", "timeout"}
    start = time.time()
    last_status = None
    while time.time() - start < max_wait_sec:
        status, data = _http("GET", f"/api/v1/workflows/{workflow_id}", timeout=10)
        if status == 200:
            cur = data.get("status")
            if cur != last_status:
                last_status = cur
            if cur in terminal_statuses:
                elapsed = round(time.time() - start, 1)
                if cur == "succeeded":
                    return {
                        "success": True,
                        "message": f"前瞻调度任务完成（用时 {elapsed} 秒）",
                        "final_status": cur,
                        "scenario_status": data.get("scenario_status"),
                        "optimization_status": data.get("optimization_status"),
                        "workflow_id": workflow_id,
                        "wait_sec": elapsed,
                    }
                return {
                    "success": False,
                    "message": f"前瞻调度任务失败: {data.get('message') or data.get('error_type') or cur}",
                    "final_status": cur,
                    "error_type": data.get("error_type"),
                    "error_detail": data.get("message"),
                    "workflow_id": workflow_id,
                    "wait_sec": elapsed,
                }
        time.sleep(poll_interval_sec)

    elapsed = round(max_wait_sec, 1)
    return {
        "success": False,
        "message": f"前瞻调度任务在 {elapsed} 秒内未完成，可能仍在后台运行",
        "final_status": "timeout",
        "workflow_id": workflow_id,
        "wait_sec": elapsed,
    }


@tool
def lasch_get_workflow_result(workflow_id: str, session_id: str = "default") -> Dict:
    """
    获取 LASCH 前瞻调度工作流的完整结果。
    【使用时机】lasch_wait_workflow 返回 success=true 后，调本工具取完整数据。
    【返回】结构包含 scenario_result（场景集合：各场景概率、负荷/新能源曲线）
           和 optimization_result（优化结果：机组出力、断面潮流、备用、风险分析等）。
           拿到后给用户解读概率加权的关键指标，不要原样粘贴大段 JSON。
    """
    status, data = _http("GET", f"/api/v1/workflows/{workflow_id}/result", timeout=30)
    if status == 200:
        scenario_result = data.get("scenario_result", {})
        optimization_result = data.get("optimization_result", {})

        summary = {
            "success": True,
            "workflow_id": workflow_id,
            "mode": data.get("mode"),
            "scenario_count": scenario_result.get("scenario_count"),
            "scenario_status": scenario_result.get("status"),
            "optimization_status": optimization_result.get("status"),
            "generator": scenario_result.get("generator", {}).get("model_version"),
            "calculation_window": scenario_result.get("calculation_window"),
        }
        if optimization_result.get("status") == "success":
            summary["message"] = "前瞻调度分析完成，场景生成与优化均成功"
        elif optimization_result.get("status") == "failed":
            summary["message"] = f"场景生成成功但优化失败: {optimization_result.get('message', '未知错误')}"
        else:
            summary["message"] = "前瞻调度结果已返回"

        summary["data"] = {
            "scenario_result": scenario_result,
            "optimization_result": optimization_result,
        }
        return summary

    return {
        "success": False,
        "message": f"获取前瞻调度结果失败（HTTP {status}）",
        "error": data,
    }


@tool
def lasch_query_status(workflow_id: str, session_id: str = "default") -> Dict:
    """
    查询 LASCH 前瞻调度工作流的当前状态。
    【注意】本工具仅用于偶尔查状态或超时后的补查。
    正常流程请使用 lasch_wait_workflow（它会自动轮询直到完成），
    不要用本工具手动循环轮询——那会反复消耗 LLM token。
    """
    status, data = _http("GET", f"/api/v1/workflows/{workflow_id}", timeout=10)
    if status == 200:
        return {
            "success": True,
            "status": data.get("status"),
            "current_stage": data.get("current_stage"),
            "scenario_status": data.get("scenario_status"),
            "optimization_status": data.get("optimization_status"),
            "error": data.get("message") if data.get("status") in ("failed", "cancelled") else None,
            "created_at": data.get("created_at"),
            "finished_at": data.get("finished_at"),
        }
    return {
        "success": False,
        "message": f"查询失败（HTTP {status}）",
        "error": data,
    }


LASCH_TOOLS = [
    lasch_health_check,
    lasch_submit_workflow,
    lasch_wait_workflow,
    lasch_get_workflow_result,
    lasch_query_status,
]