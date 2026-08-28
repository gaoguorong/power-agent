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