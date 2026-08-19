# -*- coding: utf-8 -*-
"""
电网分析智能体配置文件

定义各种默认参数和常量
"""

# 默认电网类型
DEFAULT_GRID_TYPE = "case9"

# 支持的电网类型列表
SUPPORTED_GRID_TYPES = [
    "case9",      # IEEE 9节点测试系统
    "case14",     # IEEE 14节点测试系统
    "case30",     # IEEE 30节点测试系统
    "case39",     # IEEE 39节点系统（新英格兰，手工建模，10台发电机）
    "case57",     # IEEE 57节点测试系统
    "case118",    # IEEE 118节点测试系统
    "case300",    # IEEE 300节点测试系统
    "simple",     # 自定义简单电网
]

# 潮流计算参数
POWER_FLOW_CONFIG = {
    "algorithm": "nr",           # 计算算法: nr, iwamoto_nr
    "max_iteration": 30,          # 最大迭代次数
    "tolerance": 1e-8,           # 收敛精度
    "calculate_voltage_angles": True,
    "init": "auto",              # 初始化方式
}

# 电压越限阈值
VOLTAGE_LIMITS = {
    "vmin_pu": 0.95,    # 电压下限 (pu)
    "vmax_pu": 1.05,    # 电压上限 (pu)
    "vmin_strong_pu": 0.97,  # 严格电压下限
    "vmax_strong_pu": 1.03,  # 严格电压上限
}

# 线路负载率阈值(%)
LINE_LOADING_THRESHOLDS = {
    "warning": 80.0,    # 预警阈值
    "critical": 100.0,  # 危险阈值
}

# 变压器负载率阈值(%)
TRAFO_LOADING_THRESHOLDS = {
    "warning": 80.0,
    "critical": 100.0,
}

# N-1校核配置
N1_CHECK_CONFIG = {
    "max_iterations": 30,
    "check_elements": ["line", "trafo", "bus"],
}

# 短路计算配置
SHORT_CIRCUIT_CONFIG = {
    "fault_types": ["3phase", "2phase", "1phase"],
    "default_fault_type": "3phase",
}

# 电压稳定性配置
VOLTAGE_STABILITY_CONFIG = {
    "max_load_factor": 2.0,
    "step_size": 0.1,
    "load_increase_type": "proportional",  # proportional, uniform
}

# 安全性评级标准
SAFETY_RATING_CRITERIA = {
    "safe": {
        "success_rate_min": 0.95,
        "violation_rate_max": 0.0,
    },
    "basically_safe": {
        "success_rate_min": 0.80,
        "violation_rate_max": 0.10,
    },
    "risky": {
        "success_rate_min": 0.60,
    },
    "unsafe": {
        "success_rate_min": 0.0,
    },
}

# 问题类型映射（关键词到工具）
QUESTION_KEYWORDS = {
    "power_flow": ["潮流", "潮流计算", "power flow", "PF"],
    "n1_check": ["N-1", "n-1", "N1", "安全校核", "静态安全", "断线"],
    "short_circuit": ["短路", "short circuit", "故障", "三相短路", "两相短路"],
    "voltage_stability": ["电压稳定", "稳定裕度", "P-V", "pv曲线", "电压崩溃"],
    "line_overload": ["线路过载", "过载", "负载率", "line loading"],
    "voltage_violation": ["电压越限", "越限", "电压范围", "violation"],
    "loss_analysis": ["网损", "损耗", "loss", "线损"],
    "grid_info": ["电网信息", "电网结构", "节点", "母线列表", "拓扑"],
}

# 输出格式配置
OUTPUT_CONFIG = {
    "max_data_items": 10,         # 最多显示的数据项数
    "include_summary": True,      # 是否包含摘要
    "include_raw_data": True,     # 是否包含原始数据
    "timestamp_format": "%Y-%m-%d %H:%M:%S",
}

# 智能体配置
AGENT_CONFIG = {
    "name": "电力系统静态安全分析智能体",
    "version": "1.1.0",
    "description": "基于pandapower的电网静态安全分析智能体（含拓扑/参数/知识/排序/风险/运行方式等扩展工具）",
    "author": "Power Agent",
}

# 知识库（元信息）——供 query_knowledge 工具回答"概念/准则/方法"类问题
KNOWLEDGE_BASE = {
    "voltage_range": {
        "title": "母线电压允许范围",
        "aliases": ["电压范围", "电压", "母线电压", "标称电压", "电压允许范围",
                    "电压上下限", "电压越限", "电压偏差", "正常运行电压"],
        "content": (
            "正常运行时，母线电压允许范围为 0.95 ~ 1.05 pu（即标称电压的 ±5%）；"
            "严格运行控制范围可取 0.97 ~ 1.03 pu。"
            "低于下限为'电压越下限'，高于上限为'电压越上限'。"
        ),
    },
    "n1_criteria": {
        "title": "N-1 静态安全校核准则",
        "aliases": ["n-1", "n1", "n-1准则", "安全校核", "静态安全", "校核准则",
                    "安全准则", "单一故障", "开断", "安全"],
        "content": (
            "N-1 准则指：电力系统在任一回线路、一台变压器或一座变电站（母线）"
            "因故障或检修退出运行后，电网仍能保持稳定运行，且不会出现："
            "(1) 潮流计算不收敛；(2) 任一母线电压越限（超出 0.95~1.05 pu）；"
            "(3) 任一线路或变压器过载（负载率超过 100%）。"
            "校核结果按成功率与越限/过载次数评为：安全 / 基本安全 / 有风险 / 不安全。"
        ),
    },
    "analysis_methods": {
        "title": "支持的电网分析方法",
        "aliases": ["分析方法", "支持的方法", "能做哪些分析", "分析能力", "功能",
                    "分析类型", "计算能力"],
        "content": (
            "本智能体支持以下计算：(1) 交流潮流计算——求稳态有功/无功分布；"
            "(2) N-1 静态安全校核——逐一元件开断后检查电压与过载；"
            "(3) 短路计算——三相/两相/单相故障电流；"
            "(4) 电压稳定性分析——逐步加压找电压崩溃点，给出稳定裕度与 P-V 曲线；"
            "(5) 线路过载分析——按负载率阈值统计；(6) 电压越限分析——母线电压检查；"
            "(7) 网损分析——线路与变压器有功损耗及网损率；"
            "(8) 单元件 N-1 安全分析——针对指定元件做开断分析；"
            "(9) 风险报告——汇总电压越限/线路过载并给出证据；"
            "(10) 拓扑/参数/知识查询——回答电网结构、元件参数与专业概念。"
        ),
    },
    "tools_overview": {
        "title": "可用分析工具一览",
        "aliases": ["工具", "工具列表", "有哪些工具", "工具一览", "可用工具",
                    "工具清单", "功能列表"],
        "content": (
            "潮流计算(run_ac_power_flow)、N-1校核(run_n1_security_check)、"
            "短路计算(run_short_circuit_analysis)、电压稳定性(check_voltage_stability)、"
            "线路过载(get_line_overload_summary)、电压越限(get_voltage_violation_summary)、"
            "网损分析(calculate_loss_analysis)、电网拓扑(get_grid_topology)、"
            "元件参数(get_element_params)、知识查询(query_knowledge)、"
            "排序筛选(rank_elements)、单元件N-1(analyze_element_security)、"
            "风险报告(generate_risk_report)、运行方式分析(analyze_with_outage)。"
        ),
    },
    "power_flow": {
        "title": "什么是交流潮流计算",
        "aliases": ["潮流", "交流潮流", "潮流计算", "牛顿", "牛顿拉夫逊", "潮流是什么",
                    "稳态计算", "工具参数", "输入参数", "需要哪些参数"],
        "content": (
            "交流潮流计算(AC Power Flow)是在给定发电出力、负荷与网络参数下，"
            "求解各母线电压幅值/相角及各支路有功/无功潮流的稳态计算，"
            "是几乎所有其他安全分析的基础。常用牛顿-拉夫逊(nr)算法。"
            "典型输入参数包括：(1) 算法 algorithm —— nr(牛顿-拉夫逊) / "
            "iwamoto_nr(岩本修正) / gauss_seidel 等；(2) 最大迭代次数 max_iteration；"
            "(3) 收敛精度 tolerance(如 1e-8)；(4) 基准容量 sn_mva 与各母线基准电压；"
            "(5) 发电机出力(PQ/PV 设定)、负荷功率、变压器分接头与并联无功。"
            "输出：各母线电压(pu/角度)、各支路有功/无功潮流与负载率、系统总有功损耗。"
        ),
    },
    "short_circuit": {
        "title": "短路计算说明",
        "aliases": ["短路", "故障电流", "短路电流", "短路计算", "短路类型", "三相短路"],
        "content": (
            "短路计算用于求系统发生短路故障时的故障电流。常见类型："
            "三相短路(3phase)、两相短路(2phase)、单相接地短路(1phase)。"
            "结果通常以短路容量/短路电流(kA)表示，用于设备选型与保护整定。"
        ),
    },
    "frequency": {
        "title": "系统基准参数",
        "aliases": ["基准", "频率", "基准参数", "基准容量", "电压等级", "系统参数",
                    "基准频率", "mva"],
        "content": (
            "IEEE 标准测试系统基准频率：case9/14/30/57/118/300 为 50Hz（或按 pandapower 默认），"
            "case39（新英格兰）为 60Hz、基准容量 100 MVA；电压等级以 230kV 为主。"
        ),
    },
}

# # LLM配置
# LLM_CONFIG = {
#     "api_key": "sk-c7879ad31bae4aec825a92781f4f2a02",  # 替换为你的API Key
#     "api_url": "https://api.deepseek.com/v1/chat/completions",  # 替换为你的大模型API URL
#     "model": "deepseek-chat",
#     "temperature": 0.1,  # 低温度以获得更稳定的工具选择
#     "max_tokens": 1024,
#     "timeout": 30,
# }

# LLM配置
LLM_CONFIG = {
    "api_key": "sk-ws-H.EPHHMEM.zBxO.MEUCIGXgqOSrHVwn4CTlEx4X_9ErgdPiPsR2rXJ3dQK_LptjAiEAq8_rTEGMWSXsjpdFKvl7o-OcNhJelj2XLoVQcOKAki4",  # 替换为你的API Key
    "api_url": "https://llm-bs9b0iaovdezx09s.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",  # 替换为你的大模型API URL
    "model": "qwen3.8-max",
    "temperature": 0.1,  # 低温度以获得更稳定的工具选择
    "max_tokens": 1024,
    "timeout": 30,
}