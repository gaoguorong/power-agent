# -*- coding: utf-8 -*-
"""技能定义 + SkillDef 匹配能力。

SkillDef 本质就是一个 dict（与 run_overload_relief 等按 .get() 读配置的用法完全兼容），
额外挂两个匹配方法，把“单个技能能不能跑”的判断收拢到技能自身：
  - can_run_pre(question)        前置 Fast Path：纯意图匹配（复合意图不抢跑）
  - can_run_post(question, gt)   后置触发：意图 + 电网状态双重检查
遍历技能做匹配的统一入口在 skills/router.py 的 SkillRouter。
"""
from typing import Any


class SkillDef(dict):
    """技能定义：dict + 匹配方法。所有配置项照旧用 .get() 读取。"""

    def _matches_intent(self, question: str, relax_pre_action: bool = False) -> bool:
        """对象词(triggers) 与 动作词(action_triggers) 同时命中才算意图匹配。

        relax_pre_action=False（前置拦截，默认）：
          额外检查 pre_action_triggers——若用户同时说了断线/切负荷/调负荷倍率等
          状态变更动作，说明是复合意图，Skill 不抢跑，让 LLM 先做状态变更。
        relax_pre_action=True（后置触发）：
          跳过 pre_action_triggers 排除——因为 LLM 已经执行完状态变更了，
          此时只看用户有没有对应意图，不管有没有说过断线。
        """
        if not question:
            return False
        q = question.lower()
        objs = self.get("triggers", []) or []
        acts = self.get("action_triggers", []) or []
        pre_acts = self.get("pre_action_triggers", []) or []
        if not any(w.lower() in q for w in objs):
            return False
        if acts and not any(w.lower() in q for w in acts):
            return False
        if not relax_pre_action and pre_acts:
            if any(w.lower() in q for w in pre_acts):
                return False
        return True

    def can_run_pre(self, question: str) -> bool:
        """前置 Fast Path：纯意图匹配，复合意图（含断线/切负荷等）不抢跑。"""
        return self._matches_intent(question, relax_pre_action=False)

    def can_run_post(self, question: str, gt: Any) -> bool:
        """后置触发：意图命中 + 电网已加载 + 技能各自的状态前置条件。"""
        if not self._matches_intent(question, relax_pre_action=True):
            return False
        if getattr(gt, "net", None) is None:
            return False
        return self._state_ready(gt)

    def _state_ready(self, gt: Any) -> bool:
        """技能专属的电网状态前置条件（未配置 state_ready 时默认 True）。

        注意：state_ready 在技能 dict 里只能存“注册名”字符串，不能存函数对象。
        因为 matched_skill 会被写进 LangGraph state 并由 checkpoint(msgpack)
        序列化，dict 里一旦混入函数就会报
        "Type is not msgpack serializable: function"。真正的函数放在
        模块级 _STATE_READY_FNS 注册表里，这里按名字查。
        """
        key = self.get("state_ready")
        if not key:
            return True
        fn = _STATE_READY_FNS.get(key) if isinstance(key, str) else None
        if fn is None:
            return True
        try:
            return bool(fn(self, gt))
        except Exception:
            return False


# ============================================================
# 断线后消过载：机组灵敏度再调度闭环
#   流程由下方 steps 声明（潮流→过载检查→单轮再调度→循环/结束），
#   数值细节（灵敏度排序、步长规划、回退判断）封装在 skill_runner.py
#   的 relief_round handler 中，跨轮状态由执行器上下文维护。
# ============================================================
def _overload_state_ready(skill, gt):
    """消过载状态前置：跑一次潮流确认当前确实存在过载线路。"""
    limit = float(skill.get("loading_limit_percent", 100.0))
    pf = gt.run_ac_power_flow()
    if not pf.get("success"):
        return False
    ov = gt.get_line_overload_summary(threshold=limit, skip_runpp=True)
    return bool(ov.get("success")) and ov.get("过载线路数", 0) > 0


# state_ready 注册表：技能 dict 里只存名字字符串（保证可被 checkpoint 序列化），
# 真正的判定函数集中放这里，由 SkillDef._state_ready 按名字查找调用。
_STATE_READY_FNS = {"overload_relief": _overload_state_ready}


OVERLOAD_RELIEF_SKILL = SkillDef({
    "name": "overload_relief",
    "description": "断线/工况变化后，基于机组灵敏度自动再调度，迭代调整机组出力，"
                   "直到所有线路负载率回到正常区间或达到最大轮数",
    "triggers": ["过载", "负载率", "超载", "过负荷", "线路越限"],
    "action_triggers": ["消除", "降低", "压低", "调整", "调机组", "调",
                        "恢复", "正常", "解决", "处理", "再调度", "redispatch", "不过载",
                        "修复", "消掉", "消去"],
    "pre_action_triggers": [
        "断开", "切断", "停运", "切出", "切掉",
        "投运", "投入", "投切", "合闸", "分闸",
        "切负荷", "切机",
        "负荷倍率", "调负荷", "加负荷", "减负荷", "减载",
        "负荷调到", "负荷调至", "负荷调整",
        "加载网", "加载模型", "加载电网", "加载电网模型",
    ],
    "loading_limit_percent": 100.0,
    "state_ready": "overload_relief",   # 注册名，对应 _STATE_READY_FNS，勿直接放函数
    "max_iterations": 10,            # 最多再调度轮数(兜底防死循环)
    "no_improve_limit": 2,           # 连续N轮无改善则判定调不动、停止
    "top_n_gens": 2,                 # 每轮协同调整的机组台数(按转移能力选最强)
    # 流程编排（声明式 steps）：执行器按序解释，loop 回到指定步(to,默认0)再来一轮。
    #   tool    —— 调电网工具，结果存 save（params 值以 @ 开头表示从本技能配置取）
    #   check   —— 谓词判断走 then/else 分支
    #   step_fn —— 调 skill_runner 注册的具名 handler（封装数值密集逻辑）
    #   end/loop—— 结束闭环 / 回到指定步再来一轮
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
         # relief_round 已把调整后复查的 pf/ov 写回 saved，新一轮直接做过载检查，不重算同状态
         "else": {"action": "loop", "to": 2}},
    ],
})