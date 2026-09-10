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
    # 复合意图排除：用户同时说了断线/切负荷/加载电网等前置操作时，
    # 负荷扫描不抢跑——让 LLM 先做状态变更，后置触发自然会接管扫描。
    "pre_action_triggers": [
        "断开", "切断", "停运", "切出", "切掉",
        "投运", "投入", "投切", "合闸", "分闸",
        "切负荷", "切机",
        "加载网", "加载模型", "加载电网", "加载电网模型",
    ],
    "max_iterations": 4,
    "no_improve_limit": 0,
    "factors": [2.0, 4.0],
    "overload_threshold": 100.0,  # 线路过载判定阈值(%)，100=满载
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
#   流程由下方 steps 声明（潮流→过载检查→单轮再调度→循环/结束），
#   数值细节（灵敏度排序、步长规划、回退判断）封装在 skill_runner.py
#   的 relief_round handler 中，跨轮状态由执行器上下文维护。
# ============================================================
OVERLOAD_RELIEF_SKILL = {
    "name": "overload_relief",
    "description": "断线/工况变化后，基于机组灵敏度自动再调度，迭代调整机组出力，"
                   "直到所有线路负载率回到正常区间或达到最大轮数",
    # 触发规则：对象词(triggers) 与 动作词(action_triggers) 同时命中才触发。
    # 纯“断开某线路”不含动作词，不会误触发（断线交给 LLM 的 set_element_status）。
    "triggers": ["过载", "负载率", "超载", "过负荷", "线路越限"],
    "action_triggers": ["消除", "降低", "压低", "调整", "调机组", "调",
                        "恢复", "正常", "解决", "处理", "再调度", "redispatch", "不过载",
                        "修复", "消掉", "消去"],
    # 复合意图排除：若用户同时说了"断线/切负荷/调负荷倍率"等会改变电网状态的
    # 前置操作，Skill 不抢跑——让 LLM 先把状态变更做了，后置触发自然会接管消过载。
    "pre_action_triggers": [
        "断开", "切断", "停运", "切出", "切掉",
        "投运", "投入", "投切", "合闸", "分闸",
        "切负荷", "切机",
        "负荷倍率", "调负荷", "加负荷", "减负荷", "减载",
        "负荷调到", "负荷调至", "负荷调整",
        "加载网", "加载模型", "加载电网", "加载电网模型",
    ],
    "loading_limit_percent": 100.0,  # 线路负载率正常上限(%)，100=满载
    "max_iterations": 10,            # 最多再调度轮数(兜底防死循环)
    "no_improve_limit": 2,           # 连续N轮无改善则判定调不动、停止
    "top_n_gens": 2,                 # 每轮协同调整的机组台数(按转移能力选最强)
    # 流程编排（声明式 steps）：执行器按序解释，loop 回到第一步再来一轮。
    #   tool    —— 调电网工具，结果存 save（params 值以 @ 开头表示从本技能配置取）
    #   check   —— 谓词判断走 then/else 分支
    #   step_fn —— 调 skill_runner 注册的具名 handler（封装数值密集逻辑）
    #   end/loop—— 结束闭环 / 回到第一步循环
    # ------------------------------------------------------------
    "steps": [
        {"action": "tool", "tool": "run_ac_power_flow", "save": "pf"},
        {"action": "tool", "tool": "get_line_overload_summary",
         "params": {"threshold": "@loading_limit_percent", "skip_runpp": True},
         "save": "ov"},
        {"action": "check", "check": "overload_free",
         "then": {"action": "end"},                    # 无过载/评估失败 → 结束
         "else": {"action": "step_fn", "fn": "relief_round"}},   # 有过载 → 单轮再调度
        {"action": "check", "check": "relief_finished",
         "then": {"action": "end"},                    # 收敛/停滞/恶化/达上限 → 结束
         "else": {"action": "loop"}},                  # 未定论 → 回到第 1 步再来一轮
    ],
}