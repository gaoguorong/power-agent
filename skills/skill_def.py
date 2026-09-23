from typing import Any, Callable, Dict


class SkillDef(dict):

    STATE_READY_FNS: Dict[str, Callable[..., bool]] = {}

    @classmethod
    def register_state_ready(cls, name: str):
        """登记一个 state_ready 判定函数（按名字），供技能 dict 以 "state_ready": name 引用。
        """
        def deco(fn: Callable[..., bool]) -> Callable[..., bool]:
            cls.STATE_READY_FNS[name] = fn
            return fn
        return deco

    def _matches_intent(self, question: str, relax_pre_action: bool = False) -> bool:
        """对象词(triggers) 与 动作词(action_triggers) 同时命中才算意图匹配。
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
        """
        key = self.get("state_ready")
        if not key:
            return True
        fn = self.STATE_READY_FNS.get(key) if isinstance(key, str) else None
        if fn is None:
            return True
        try:
            return bool(fn(self, gt))
        except Exception:
            return False
