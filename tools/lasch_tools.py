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
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for _fname in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
    try:
        font_manager.findfont(_fname, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_fname]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False
from langchain_core.tools import tool

LASCH_BASE = os.environ.get("LASCH_API_BASE", "http://127.0.0.1:18080")
LASCH_TOKEN = os.environ.get("LASCH_API_TOKEN", "")

_CHARTS_DIR = Path(__file__).resolve().parents[1] / "charts"
_CHARTS_DIR.mkdir(parents=True, exist_ok=True)

_WORKFLOW_CHART_FLAGS: Dict[str, bool] = {}


_FOCUS_ATTRIBUTE_PRESETS = {
    "reserve": ("system", "system"),
    "curtailment": ("system", "system"),
    "section_flow_risk": ("system", "all_sections"),
    "flow": ("section", None),
    "margin": ("section", None),
}
_KNOWN_FOCUS_ATTRIBUTES = set(_FOCUS_ATTRIBUTE_PRESETS.keys())


def _build_focus_from_attr(attr: str, provided_name: Optional[str]) -> Dict:
    attr = (attr or "").strip().lower()
    if attr in _FOCUS_ATTRIBUTE_PRESETS:
        obj_type, preset_name = _FOCUS_ATTRIBUTE_PRESETS[attr]
        if preset_name is not None:
            object_name = preset_name
        else:
            object_name = provided_name if provided_name else "all_sections"
        return {"object_type": obj_type, "object_name": object_name, "attribute": attr}
    return {
        "object_type": "system",
        "object_name": provided_name if provided_name else "system",
        "attribute": attr,
    }


def _normalize_focus_item(item) -> Optional[Dict]:
    if isinstance(item, str):
        return _build_focus_from_attr(item, provided_name=None)
    if isinstance(item, dict):
        attr = None
        for key in ("attribute", "attr", "type"):
            val = item.get(key)
            if isinstance(val, str) and val.strip().lower() in _KNOWN_FOCUS_ATTRIBUTES:
                attr = val.strip().lower()
                break
        if attr is None:
            for key in ("attribute", "attr", "type"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    attr = val.strip().lower()
                    break
        provided_name = None
        for key in ("object_name", "name", "object"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                provided_name = val.strip()
                break
        return _build_focus_from_attr(attr or "reserve", provided_name)
    return None


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
    load_adjustment_mw: float = 0.0,
    renewable_adjustment_mw: float = 0.0,
    unit_output_constraints: Optional[str] = None,
    section_flow_constraints: Optional[str] = None,
    adjustment_chart: bool = False,
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
        focus_results:     重点关注结果，JSON 数组字符串，如 '["reserve"]' 或
                           '["reserve","curtailment","section_flow_risk"]'。
                           支持的属性：reserve(系统备用)、curtailment(新能源弃电)、
                           section_flow_risk(全网断面风险)、flow(指定断面潮流)、
                           margin(指定断面裕度)。也可以传对象数组，如
                           '[{"object_type":"system","object_name":"system","attribute":"reserve"}]'。
                           不需要就直接不传该参数
        load_adjustment_mw:  系统负荷调整量（MW），正数=上调，负数=下调，0=不调整。
                             该调整量会施加到关注时段内的所有时间步。例如用户说"负荷全时段上调600MW"就填 600.0。
        renewable_adjustment_mw: 新能源（风电+光伏）出力调整量（MW），正数=上调，负数=下调，0=不调整。
        unit_output_constraints: 机组出力约束，JSON 数组字符串。当用户提到修改某机组的出力上限/下限/出力范围时使用。
                             每个元素为一个对象，必须包含 unit_name（机组全名，如 "甘肃.平凉二厂/22kV.#5机"）和 constraint_type。
                             constraint_type="range" 时需传 min_mw 和 max_mw（出力上下限，单位MW）；
                             constraint_type="fixed" 时需传 value_mw（固定出力，单位MW）。
                             示例：'[{"unit_name":"甘肃.平凉二厂/22kV.#5机","constraint_type":"range","min_mw":260,"max_mw":420}]'
                             不需要就不传该参数。
        section_flow_constraints: 断面潮流限额约束，JSON 数组字符串。当用户提到收紧/修改某断面的限额时使用。
                             每个元素为一个对象，必须包含 section_name（断面全名，如 "基态-750泉鱼断面B"）和 constraint_type。
                             constraint_type="tighten" 时需传 limit_ratio（限额比例，0~1之间，如收紧5%传 0.95）；
                             constraint_type="custom" 时需传 limit_mw（自定义限额，单位MW）。
                             示例（收紧5%）：'[{"section_name":"基态-750泉鱼断面B","constraint_type":"tighten","limit_ratio":0.95}]'
                             示例（自定义限额）：'[{"section_name":"基态-750泉鱼断面B","constraint_type":"custom","limit_mw":1500}]'
                             不需要就不传该参数。
        adjustment_chart:  是否生成负荷/新能源调整对比图。默认 false。
                             【重要判断规则】只有当**本次用户提问明确提到**了负荷或新能源的调整
                             （如"负荷上调300MW"、"新能源下调200MW"）时，才设为 true。
                             如果本次只是"重新优化"、"再分析"等且没有新的负荷/新能源调整，
                             即使继承了之前的 load_adjustment_mw，也必须设为 false（不生成对比图）。
                             因为对比图展示的是"本次调整的变化量"，继承的参数不算本次调整。
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
    if trade_time and trade_time.strip().lower() not in ("none", "null", ""):
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
        normalized_focus = []
        for f in focus_list:
            item = _normalize_focus_item(f)
            if item is not None:
                normalized_focus.append(item)
        if normalized_focus:
            requirement["analysis_focus"] = normalized_focus

    boundary_modifications: Dict = {}
    if load_adjustment_mw:
        boundary_modifications["load_forecast"] = {"delta_mw": float(load_adjustment_mw)}
    if renewable_adjustment_mw:
        boundary_modifications["renewable_forecast"] = {"delta_mw": float(renewable_adjustment_mw)}
    if boundary_modifications:
        requirement["boundary_modifications"] = boundary_modifications

    constraint_modifications: Dict = {}
    if unit_output_constraints:
        try:
            parsed = json.loads(unit_output_constraints) if isinstance(unit_output_constraints, str) else unit_output_constraints
            if isinstance(parsed, list) and parsed:
                constraint_modifications["unit_output_constraints"] = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if section_flow_constraints:
        try:
            parsed = json.loads(section_flow_constraints) if isinstance(section_flow_constraints, str) else section_flow_constraints
            if isinstance(parsed, list) and parsed:
                constraint_modifications["section_flow_constraints"] = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if constraint_modifications:
        requirement["constraint_modifications"] = constraint_modifications

    body: Dict = {
        "mode": mode,
        "requirement": requirement,
        "scenario_control": {"scenario_count": scenario_count, "seed": 20},
    }
    status, data = _http("POST", "/api/v1/workflows", body=body)
    if status == 202:
        result = {
            "success": True,
            "message": "前瞻调度任务已提交，正在后台执行",
            "workflow_id": data.get("workflow_id"),
            "submission_id": data.get("submission_id"),
            "mode": mode,
            "scenario_count": scenario_count,
            "time_window": f"{time_window_start} ~ {time_window_end}",
        }
        constraint_summary: Dict = {}
        if boundary_modifications:
            constraint_summary["boundary"] = boundary_modifications
        if constraint_modifications:
            constraint_summary["constraints"] = constraint_modifications
        if constraint_summary:
            result["applied_constraints"] = constraint_summary
            result["message"] += "（已生效的调整见 applied_constraints）"
        _WORKFLOW_CHART_FLAGS[data.get("workflow_id")] = bool(adjustment_chart)
        return result
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


def _build_adjustment_chart(base_forecast: Dict) -> Optional[str]:
    """
    当存在负荷或新能源调整时，生成修改前/修改后对比曲线并保存为 PNG 文件。
    横坐标为时间轴，纵坐标为功率(MW)，两条曲线分别表示修改前和修改后，
    中间用箭头标注变化量。
    返回可访问的 URL 路径（如 /charts/xxx.png），无调整时返回 None。
    """
    if not base_forecast:
        return None
    series = base_forecast.get("series") or {}
    time_axis = base_forecast.get("time_axis") or []
    load_delta = float(base_forecast.get("load_delta_mw") or 0.0)
    renewable_delta = float(base_forecast.get("renewable_delta_mw") or 0.0)

    has_load_adj = abs(load_delta) > 1e-6
    has_renewable_adj = abs(renewable_delta) > 1e-6
    if not (has_load_adj or has_renewable_adj):
        return None
    if not time_axis:
        return None

    n_plots = (1 if has_load_adj else 0) + (1 if has_renewable_adj else 0)
    fig, axes = plt.subplots(n_plots, 1, figsize=(11, 4.2 * n_plots), squeeze=False)
    axes = axes.flatten()
    ax_idx = 0

    x = list(range(len(time_axis)))
    tick_step = max(1, len(time_axis) // 8)

    def _plot_one(ax, original, modified, delta, title, color_after):
        ax.plot(x, original, color="#9ca3af", linestyle="--", linewidth=2, label="修改前", marker="o", markersize=4)
        ax.plot(x, modified, color=color_after, linestyle="-", linewidth=2.4, label="修改后", marker="s", markersize=4)
        mid = len(x) // 2
        y0 = original[mid]
        y1 = modified[mid]
        y_arrow = (y0 + y1) / 2
        ax.annotate(
            "",
            xy=(mid, y1),
            xytext=(mid, y0),
            arrowprops=dict(arrowstyle="->", color="#dc2626", lw=2.5),
        )
        sign = "+" if delta >= 0 else ""
        ax.text(
            mid + 0.3, y_arrow,
            f"Δ={sign}{delta:.0f} MW",
            fontsize=11, color="#dc2626", fontweight="bold",
            va="center",
        )
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_ylabel("功率 (MW)", fontsize=11)
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels([time_axis[i][5:] for i in x[::tick_step]], rotation=30, ha="right")
        ax.legend(loc="best", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.margins(x=0.02)

    if has_load_adj:
        load_orig = series.get("load_mw_original") or series.get("load_mw") or []
        load_mod = series.get("load_mw") or []
        if load_orig and load_mod and len(load_orig) == len(load_mod) == len(time_axis):
            _plot_one(axes[ax_idx], load_orig, load_mod, load_delta, "系统负荷预测：修改前 vs 修改后", "#2563eb")
            ax_idx += 1

    if has_renewable_adj:
        re_orig = series.get("renewable_mw_original") or series.get("renewable_mw") or []
        re_mod = series.get("renewable_mw") or []
        if re_orig and re_mod and len(re_orig) == len(re_mod) == len(time_axis):
            _plot_one(axes[ax_idx], re_orig, re_mod, renewable_delta, "新能源出力预测：修改前 vs 修改后", "#16a34a")
            ax_idx += 1

    plt.tight_layout()
    filename = f"adjustment_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    filepath = _CHARTS_DIR / filename
    fig.savefig(str(filepath), format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"/charts/{filename}"


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
        scenario_result = data.get("scenario_result") or {}
        optimization_result = data.get("optimization_result") or {}
        mode = data.get("mode")
        is_scenario_only = mode == "scenario_only"

        summary = {
            "success": True,
            "workflow_id": workflow_id,
            "mode": mode,
            "scenario_count": scenario_result.get("scenario_count"),
            "scenario_status": scenario_result.get("status"),
            "optimization_status": optimization_result.get("status"),
            "generator": (scenario_result.get("generator") or {}).get("model_version"),
            "calculation_window": scenario_result.get("calculation_window"),
        }

        base_forecast = scenario_result.get("base_forecast")
        adjustment_chart = None
        need_chart = _WORKFLOW_CHART_FLAGS.get(workflow_id, False)
        if base_forecast and need_chart:
            try:
                adjustment_chart = _build_adjustment_chart(base_forecast)
            except Exception:
                adjustment_chart = None
        if adjustment_chart:
            summary["adjustment_chart_url"] = adjustment_chart

        if is_scenario_only:
            summary["message"] = (
                "场景生成完成（scenario_only 模式，未执行优化）"
                if scenario_result.get("status") == "success"
                else f"场景生成失败: {scenario_result.get('message', '未知错误')}"
            )
        elif optimization_result.get("status") == "success":
            base_msg = "前瞻调度分析完成，场景生成与优化均成功"
            if adjustment_chart:
                base_msg += f"\n本次涉及负荷/新能源调整，已生成对比图：{adjustment_chart}\n请在回答正文中独占一行原样输出该图片URL（不要加任何前缀文字），前端会自动渲染为图片。"
            else:
                base_msg += "\n本次未涉及负荷/新能源功率调整，无对比图，不要在回答中输出任何 /charts/ 图片URL。"
            summary["message"] = base_msg
        elif optimization_result.get("status") == "failed":
            summary["message"] = f"场景生成成功但优化失败: {optimization_result.get('message', '未知错误')}"
        else:
            summary["message"] = "前瞻调度结果已返回"

        summary["data"] = {
            "scenario_result": scenario_result,
            "optimization_result": optimization_result,
        }
        if adjustment_chart:
            summary["data"]["adjustment_chart_url"] = adjustment_chart
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


@tool
def lasch_submit_section_control(
    time_window_start: str,
    time_window_end: str,
    primary_section: str,
    primary_max_pct: float = 92.0,
    other_sections_max_pct: float = 100.0,
    step_min: int = 15,
    task_name: str = "前瞻调度断面局部控制",
    session_id: str = "default",
) -> Dict:
    """
    提交 LASCH 断面局部控制任务：在指定时段内把某一目标断面的潮流负载率降到指定阈值以下，
    同时保证其它断面不超过次级阈值。后端在内部用平衡灵敏度再调度（上调一台机组+下调另一台、
    保持总功率平衡）自动给出增减出力建议。
    【触发条件】用户输入包含"断面控制"/"断面潮流"/"消断面过载"/"泉鱼断面"等关键词时调用本工具。
    【必填】time_window_start / time_window_end（格式 "2025-10-03 17:00"）、primary_section（目标断面名，
            如 "基态-750泉鱼断面B"）。时间窗口务必让用户给出，不要瞎填。
    【参数】
        time_window_start: 关注时段开始，如 "2025-10-03 17:00"
        time_window_end:   关注时段结束，如 "2025-10-03 19:30"
        primary_section:   要压负荷率的断面全名，如 "基态-750泉鱼断面B"
        primary_max_pct:    主目标断面的负载率上限百分比，默认 92.0
        other_sections_max_pct: 其它断面的负载率上限百分比（次目标），默认 100.0
        step_min:          时间步长（分钟），默认 15
        task_name:         任务标签（给用户看）
    【返回】
        成功: {"success": true, "request_id": "req_xxx", "task_kind": "section_control", ...}
              —— 记下来，立刻调 lasch_wait_section_control 等结果。
        失败: {"success": false, "message": "...", "error": ...}
    """
    requirement: Dict = {
        "schema_version": "st_section_control_requirement_v1",
        "task_type": "局部断面控制",
        "task_name": task_name,
        "input_text": f"在 {time_window_start}~{time_window_end} 期间将断面 {primary_section} 控制到 {primary_max_pct}% 以下，"
                      f"其它断面不超过 {other_sections_max_pct}%",
        "time_window": {
            "start": time_window_start,
            "end": time_window_end,
            "step_min": step_min,
        },
        "primary_target": {
            "section_name": primary_section,
            "max_load_rate_pct": primary_max_pct,
        },
        "secondary_targets": [
            {
                "scope": "other_sections",
                "max_load_rate_pct": other_sections_max_pct,
            }
        ],
    }
    body: Dict = {"requirement": requirement}
    status, data = _http("POST", "/api/v1/section-controls", body=body)
    if status == 202:
        return {
            "success": True,
            "message": "断面局部控制任务已提交，正在后台执行",
            "request_id": data.get("request_id"),
            "task_kind": data.get("task_kind"),
            "status": data.get("status"),
            "calculation_window": data.get("calculation_window"),
            "time_window": f"{time_window_start} ~ {time_window_end}",
            "primary_section": primary_section,
            "primary_max_pct": primary_max_pct,
            "warnings": data.get("warnings") or [],
        }
    return {
        "success": False,
        "message": f"提交断面控制任务失败",
        "http_status": status,
        "error": data,
    }


@tool
def lasch_wait_section_control(
    request_id: str,
    max_wait_sec: int = 300,
    poll_interval_sec: int = 3,
    session_id: str = "default",
) -> Dict:
    """
    阻塞等待 LASCH 断面局部控制任务完成（代码层轮询，不会消耗 LLM token）。
    【使用时机】lasch_submit_section_control 返回 request_id 后，立刻调本工具等结果。
    【不要】手动循环查询状态来等待——那会反复消耗 LLM token。
    【参数】
        request_id:     submit 返回的 request_id（形如 "req_20261023..."）
        max_wait_sec:   最长等待秒数，默认300（断面控制通常几十秒就完）
        poll_interval_sec: 轮询间隔，默认3秒
    【返回】
        成功: {"success": true, "final_status": "succeeded", "wait_sec": 12.3, ...}
        失败: {"success": false, "final_status": "failed", "message": "...", "wait_sec": ...}
        超时: {"success": false, "final_status": "timeout", "message": "...", "wait_sec": ...}
    """
    terminal_statuses = {"succeeded", "failed", "cancelled", "timeout"}
    start = time.time()
    last_status = None
    while time.time() - start < max_wait_sec:
        status, data = _http("GET", f"/api/v1/tasks/{request_id}", timeout=10)
        if status == 200:
            cur = data.get("status")
            if cur != last_status:
                last_status = cur
            if cur in terminal_statuses:
                elapsed = round(time.time() - start, 1)
                if cur == "succeeded":
                    return {
                        "success": True,
                        "message": f"断面局部控制完成（用时 {elapsed} 秒）",
                        "final_status": cur,
                        "request_id": request_id,
                        "wait_sec": elapsed,
                    }
                return {
                    "success": False,
                    "message": f"断面局部控制失败: {data.get('message') or cur}",
                    "final_status": cur,
                    "error_type": data.get("error_type"),
                    "error_detail": data.get("message"),
                    "request_id": request_id,
                    "wait_sec": elapsed,
                }
        time.sleep(poll_interval_sec)

    elapsed = round(max_wait_sec, 1)
    return {
        "success": False,
        "message": f"断面局部控制任务在 {elapsed} 秒内未完成，可能仍在后台运行",
        "final_status": "timeout",
        "request_id": request_id,
        "wait_sec": elapsed,
    }


@tool
def lasch_get_section_control_result(request_id: str, session_id: str = "default") -> Dict:
    """
    获取 LASCH 断面局部控制任务的完整结果（含控制前后负载率、平衡增减出力建议、未解决约束等）。
    【使用时机】lasch_wait_section_control 返回 success=true 后，调本工具取数据。
    【返回结构】
        summary: 关键摘要——任务状态、主目标断面名、控制前/后最大负载率百分比、是否达标；
                 次目标（其它断面）前/后最高负载率、是否有越限；
                 unresolved_constraints（数组，空=全部约束满足）。
        control_actions: 平衡增减出力建议列表，每条含时间点、增发机组（名称+ID）、
                 减发机组、增减 MW 量；按实际执行顺序排列。
        affected_sections: 受本次再调度影响的断面清单，含潮流变化幅度和前/后负载率。
        method:  使用的控制方法说明（平衡灵敏度再调度、线性灵敏度假设等）。
        raw:     后端完整原始 JSON（含各时段的 flow_before/flow_after 数组，较占 token，
                 仅在用户明确问"每个时段"时才去读它）。
    """
    status, data = _http("GET", f"/api/v1/tasks/{request_id}/result", timeout=30)
    if status != 200:
        return {
            "success": False,
            "message": f"获取断面控制结果失败（HTTP {status}）",
            "error": data,
        }

    primary = data.get("primary_target", {})
    secondary = data.get("secondary_guardrail", {})
    actions = data.get("control_actions", [])
    unresolved = data.get("unresolved_constraints", [])

    summary = {
        "success": True,
        "request_id": request_id,
        "status": data.get("status"),
        "task_name": data.get("task_name"),
        "trade_id": data.get("trade_id"),
        "calculation_window": data.get("calculation_window"),
        "network_snapshot": data.get("network_snapshot"),
        "message": "断面局部控制结果已返回，请依据下面的摘要和控制动作给用户组织自然语言说明。",
    }

    primary_section_name = primary.get("section_name")
    primary_before = primary.get("maximum_before_pct")
    primary_after = primary.get("maximum_after_pct")
    summary["primary_target_summary"] = {
        "section_name": primary_section_name,
        "max_load_rate_before_pct": primary_before,
        "max_load_rate_after_pct": primary_after,
        "reduction_pct": round(primary_before - primary_after, 3)
            if primary_before is not None and primary_after is not None else None,
        "target_pct": primary.get("max_load_rate_pct"),
        "satisfied": primary.get("satisfied"),
    }

    if secondary:
        summary["secondary_target_summary"] = {
            "scope": secondary.get("scope"),
            "max_load_rate_pct": secondary.get("max_load_rate_pct"),
            "max_load_rate_before_pct": secondary.get("maximum_before_pct"),
            "max_load_rate_after_pct": secondary.get("maximum_after_pct"),
            "violation_count_before": secondary.get("violation_count_before"),
            "violation_count_after": secondary.get("violation_count_after"),
            "satisfied": secondary.get("satisfied"),
        }

    summary["unresolved_constraints"] = unresolved
    summary["all_constraints_satisfied"] = (
        not unresolved
        and primary.get("satisfied") is True
        and (secondary.get("satisfied") if secondary else True)
    )

    summary["control_actions_count"] = len(actions)
    summary["total_adjustment_mw"] = round(
        sum(float(a.get("adjustment_mw", 0)) for a in actions), 3
    ) if actions else 0.0

    control_actions = []
    for a in actions:
        inc = a.get("increase_resource", {})
        dec = a.get("decrease_resource", {})
        control_actions.append({
            "time": a.get("time"),
            "increase": {
                "name": inc.get("resource_name"),
                "resource_id": inc.get("resource_id"),
            },
            "decrease": {
                "name": dec.get("resource_name"),
                "resource_id": dec.get("resource_id"),
            },
            "adjustment_mw": a.get("adjustment_mw"),
            "primary_section": a.get("primary_section"),
            "load_rate_before_pct": a.get("controlled_load_rate_before_pct"),
            "load_rate_after_pct": a.get("controlled_load_rate_after_pct"),
        })
    summary["control_actions"] = control_actions

    affected = data.get("affected_sections", [])
    summary["affected_sections"] = [
        {
            "section_name": s.get("section_name"),
            "max_flow_change_mw": s.get("maximum_flow_change_mw"),
            "max_load_rate_before_pct": s.get("maximum_load_rate_before_pct"),
            "max_load_rate_after_pct": s.get("maximum_load_rate_after_pct"),
        }
        for s in affected
    ]

    summary["method"] = data.get("method")

    summary["raw"] = data

    return summary


LASCH_TOOLS = [
    lasch_health_check,
    lasch_submit_workflow,
    lasch_wait_workflow,
    lasch_get_workflow_result,
    lasch_query_status,
    lasch_submit_section_control,
    lasch_wait_section_control,
    lasch_get_section_control_result,
]