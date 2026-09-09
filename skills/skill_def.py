VOLTAGE_CORRECTION_SKILL = {
    "name": "voltage_correction",
    "description": "潮流计算后自动修正电压越限，直到合格或达到最大迭代次数",
    "triggers": ["电压越限", "越限修复", "电压调整", "电压修正", "消除越限"],
    "max_iterations": 10,
    "no_improve_limit": 3,
    "steps": [
        {"action": "tool",  "tool": "run_ac_power_flow",          "save": "pf"},
        {"action": "tool",  "tool": "get_voltage_violation_summary", "params": {"skip_runpp": True}, "save": "viol"},
        {"action": "check", "check": "violations_exist",
         "then":  {"action": "tool", "tool": "apply_voltage_correction", "save": "corr"},
         "else":  {"action": "end"}},
        {"action": "check", "check": "correction_succeeded",
         "then":  {"action": "end"},
         "else":  {"action": "loop"}},
    ],
}

LOAD_SWEEP_SKILL = {
    "name": "load_sweep",
    "description": "按指定倍率逐步提升负荷，分析各倍率下的线路过载情况",
    "triggers": [
        "负荷倍率", "负荷扫描", "负荷水平", "负荷调整", "加载分析", "负荷增长",
        "负荷调高", "负荷调到", "调负荷", "加大负荷", "增大负荷", "增加负荷",
        "负荷增加", "负荷放大", "加载", "加负荷", "提负荷", "负荷提升",
        "倍率", "几倍", "调大", "调高",
    ],
    "max_iterations": 4,
    "no_improve_limit": 0,
    "factors": [2.0, 4.0],
    "steps": [
        {"action": "tool",  "tool": "set_load_scale", "params": {"factor": 2.0}, "save": "scale_2x"},
        {"action": "tool",  "tool": "run_ac_power_flow", "save": "pf_2x", "tolerant": True},
        {"action": "tool",  "tool": "get_line_overload_summary", "params": {"skip_runpp": True}, "save": "overload_2x", "tolerant": True},
        {"action": "tool",  "tool": "set_load_scale", "params": {"factor": 4.0}, "save": "scale_4x"},
        {"action": "tool",  "tool": "run_ac_power_flow", "save": "pf_4x", "tolerant": True},
        {"action": "tool",  "tool": "get_line_overload_summary", "params": {"skip_runpp": True}, "save": "overload_4x", "tolerant": True},
    ],
}

# ============================================================
# 断线后消过载：机组灵敏度再调度闭环
#   与上面两个“声明式 steps”技能不同，本技能含“算灵敏度→选正负最大机组→自适应
#   步长一升一降→重算→判区间→循环”这类带数值判断的闭环，用字典 DSL 难以表达，
#   因此这里只登记元信息(触发词/阈值/迭代上限)，真正的编排逻辑在 skills/skill_runner.py。
# ============================================================
OVERLOAD_RELIEF_SKILL = {
    "name": "overload_relief",
    "description": "断线/工况变化后，基于机组灵敏度自动再调度，迭代调整机组出力，"
                   "直到所有线路负载率回到正常区间或达到最大轮数",
    # 触发规则：对象词(triggers) 与 动作词(action_triggers) 同时命中才触发。
    # 纯“断开某线路”不含动作词，不会误触发（断线交给 LLM 的 set_element_status）。
    "triggers": ["过载", "负载率", "超载", "过负荷", "线路越限"],
    "action_triggers": ["消除", "降低", "压低", "调整", "调机组", "恢复", "正常",
                        "解决", "处理", "再调度", "redispatch", "不过载"],
    "loading_limit_percent": 100.0,  # 负载率正常区间上限(%)
    "max_iterations": 10,            # 最多调整轮数(兜底防死循环)
    "no_improve_limit": 2,           # 连续N轮最大负载率无下降则判定调不动、停止
    "step_mw": 10.0,                 # 无自适应依据时的兜底步长(MW)
    "min_step_mw": 1.0,              # 单台机组最小有效调整量(MW)
    "max_step_mw": 300.0,            # 单台机组单轮调整上限(MW)，主要靠机组可调容量约束
    "top_n_gens": 2,                 # 每轮针对目标线路协同调整的机组台数(按转移能力选最强)
    "delta_mw": 5.0,                 # 灵敏度扰动步长(MW)
    "max_gens": 30,                  # 灵敏度计算最多参与机组数
}