# -*- coding: utf-8 -*-
"""
面向前端的静态选项：电网下拉框、快捷问题模板。
由 /api/config/options 接口下发；只保留后端真正支持的电网类型。
"""
from typing import Dict, List

from config.model_config import SUPPORTED_GRID_TYPES

# 电网下拉框选项（value 必须与 SUPPORTED_GRID_TYPES 对得上）
GRID_OPTIONS: List[Dict[str, str]] = [
    {"value": "case9",   "label": "IEEE 9节点",      "desc": "最小算例，快速体验（推荐新手/调试用）"},
    {"value": "case14",  "label": "IEEE 14节点",     "desc": "小型系统，教学常用"},
    {"value": "case30",  "label": "IEEE 30节点",     "desc": "中型系统，兼顾速度与复杂度（推荐）"},
    {"value": "case39",  "label": "新英格兰39节点",  "desc": "经典60Hz系统，标准测试集"},
    {"value": "case57",  "label": "IEEE 57节点",     "desc": "中大型系统"},
    {"value": "case118", "label": "IEEE 118节点",    "desc": "大型系统，计算较慢"},
    {"value": "case300", "label": "IEEE 300节点",    "desc": "超大型，计算可能较慢"},
]
GRID_OPTIONS = [g for g in GRID_OPTIONS if g["value"] in set(SUPPORTED_GRID_TYPES)]

# 快捷问题模板（前端渲染成快捷按钮）
QUICK_QUESTIONS: List[Dict[str, str]] = [
    {"label": "潮流计算",   "example": "基于30节点系统做潮流计算，检查过载和电压越限"},
    {"label": "N-1校核",    "example": "用30节点系统做N-1静态安全校核，识别风险线路"},
    {"label": "低电压分析", "example": "case30做潮流，找出电压低于0.95p.u.的母线"},
    {"label": "重过载分析", "example": "在case30系统中找出所有负载率>80%的线路"},
    {"label": "负荷波动",   "example": "把case30的总负荷放大到1.5倍，再做一次潮流看是否过载"},
    {"label": "最优潮流",   "example": "用30节点系统运行最优潮流OPF，目标是最小化发电成本"},
    {"label": "故障诊断",   "example": "在case30系统中假设线路5-8断开，分析潮流转移和越限情况"},
    {"label": "无功优化",   "example": "对case30系统进行无功优化，给出母线电压和发电机无功出力"},
    {"label": "供电能力",   "example": "计算case30系统的供电能力，说明最大可承载负荷"},
    {"label": "新能源接入", "example": "在case30的某节点接入风电100MW，评估对系统潮流影响"},
    {"label": "故障恢复",   "example": "case30系统某线路故障断开，给出最优转供恢复方案"},
    {"label": "灵敏度分析", "example": "分析case30系统中关键线路潮流对负荷变化的灵敏度"},
]
