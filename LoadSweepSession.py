from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class LoadSweepSession:
    """问答式负荷扫描的会话状态（唯一数据源）

    scenarios: 倍率 → 场景结果，场景字段见 _compute_scenario
    """
    active: bool = False
    grid_type: Optional[str] = None
    scenarios: Dict[float, Dict] = field(default_factory=dict)

    def latest(self) -> Optional[Dict]:
        """取倍率最高的场景"""
        return self.scenarios[max(self.scenarios)] if self.scenarios else None

    def ingest_batch_result(self, scenario_log: List[Dict], grid_type: str) -> None:
        """合并批量负荷扫描结果，供后续问答式追问直接复用"""
        for item in scenario_log:
            factor = item.get("倍率")
            if factor is None:
                continue
            self.scenarios[factor] = {
                "倍率": factor,
                "潮流收敛": item.get("潮流收敛", True),
                "总线路数": item.get("总线路数", 0),
                "过载线路数": item.get("过载线路数", 0),
                "过载线路": item.get("过载详情", []),
                "错误信息": item.get("错误信息", ""),
            }
        self.grid_type = grid_type
        self.active = bool(self.scenarios)