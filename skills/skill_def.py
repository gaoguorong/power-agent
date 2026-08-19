# -*- coding: utf-8 -*-
"""
Skill定义文件

Skill是可被引擎解释执行的声明式工作流。
每个Skill定义：
  - triggers: 触发关键词（供路由器匹配意图）
  - steps:    有序步骤列表，引擎逐行解释执行
  - max_iterations: 循环类step的最大迭代次数
  - no_improve_limit: 震荡检测阈值（连续N次无改善则提前终止）

Step类型：
  {"action": "tool",   "tool": "<工具名>", "save": "<state键>"}
      → 调用 grid_tools.execute_tool(tool)，结果存入 state[save]

  {"action": "check",  "check": "<检查名>",
   "then":  {"action": "tool", "tool": "<工具名>", "save": "<state键>"},
   "else":  {"action": "end"}}
      → 根据 then / else 分支继续执行

  {"action": "loop"}
      → 跳回第0步，迭代计数+1；达到max_iterations则终止

  {"action": "end"}
      → 立即终止执行

State机制：
  - 每个tool step的返回值存入 state[save]
  - 后续check step通过 _SKILL_CHECKS 读取state判断条件
  - 引擎内置震荡检测：跟踪 state["viol"].越限母线数 的改善情况
"""

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