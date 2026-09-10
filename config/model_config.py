# -*- coding: utf-8 -*-
"""
电网分析智能体配置文件

定义各种默认参数和常量
所有配置直接写在此文件，便于统一管理。
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
            "风险报告(generate_risk_report)、运行方式分析(analyze_with_outage)、"
            "元件投运状态修改(set_element_status，真断开/投入，持久生效)。"
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

# ==================== LLM 配置 ====================
# 切换模型：修改下面 ACTIVE_LLM 的值为 "maas" 或 "ollama" 即可
ACTIVE_LLM = "maas"

# 阿里云百炼（原默认配置）
LLM_CONFIG_MAAS = {
    "api_key": "sk-ws-H.EXIXEPM.JbDn.MEQCIAdbYMQfMaitX5XRyTTC2qepM-RhujISJKjMGQkRmFVgAiAxV6eWpZMjzopYG6ceG7SEYCtJM4AGqXMTb3KQUPhQsA",
    "api_url": "https://llm-bs9b0iaovdezx09s.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "model": "qwen3.7-flash-2026-07-15",
    "temperature": 0.1,
    "max_tokens": 2048,
    "timeout": 60,
}

# Ollama 本地部署（千问 27b）
LLM_CONFIG_OLLAMA = {
    "api_key": "ollama",
    "api_url": "http://localhost:11434/v1",
    "model": "qwen2.5:72b",
    "temperature": 0.1,
    "max_tokens": 4096,
    "timeout": 120,
}

# 对外统一暴露：根据 ACTIVE_LLM 指向当前活跃的配置
LLM_CONFIG = LLM_CONFIG_OLLAMA if ACTIVE_LLM == "ollama" else LLM_CONFIG_MAAS
SYSTEM_PROMPT = (
    "你是专业的电网静态安全分析助手，必须用提供的原子工具分步回答用户问题。"
    ""
    "【1. 工具调用铁律】"
    "· 计算类任务（建网/潮流/过载/电压/N-1/风险/损耗）必须调工具，禁止凭知识编数据。"
    "· 计算前必须先调 create_test_grid（用户说xx节点=指定电网类型，映射："
    "  9节点=case9  14节点=case14  30节点=case30  39节点=case39"
    "  57节点=case57  118节点=case118  300节点=case300  简单=simple）。"
    "· 用户要用【真实电网/实际电网模型/指定文件】（如 nankao_net、开封实际电网、"
    "  某个 .json/.p/.xlsx 电网文件）→ 调 load_grid_from_file(file_path)，不要用 create_test_grid。"
    "  只给文件名时会自动在“实际电网数据”目录下查找；加载后即可照常调潮流/过载/电压/N-1 等工具。"
    "· 用户要【真的断开/退出某线路·变压器·母线，再重新算潮流、看断开前后对比】"
    "  （如“断开苗余线，重新计算潮流”）→ 调 set_element_status(element_type, element_ids, in_service=False)"
    "  真实改状态，再调 run_ac_power_flow + get_line_overload_summary/get_voltage_violation_summary 分析；"
    "  复原传 in_service=True。此改动会影响后续所有分析。"
    "· 用户只是【假想某元件退出、看这一次结果、不改变后续电网】（如“假设线路5退出会怎样”）"
    "  → 调 analyze_with_outage（副本上算，不影响电网）；要逐个扫描全部元件用 run_n1_security_check。"
    "  判据：是否影响后续分析——影响=set_element_status，不影响=analyze_with_outage。"
    "· 多步任务必须「一次一轮，分步调用」：工具结果返回后，再判断下一步调什么。"
    "· 问定义/规程（如什么是N-1准则）→ 调 query_knowledge，不调计算工具。"
    ""
    "【2. 最小化原则：只做用户明确要求的，不要自作主张加戏】"
    "· 用户的问题里提到了什么，你就调对应的工具；没提到的，一律不要追加。"
    "· 例如：用户只提「潮流计算」→ 建网+算潮流即可，不要顺手去查过载或电压。"
    "· 只有用户明确说「全面分析/安全评估/检查所有问题」等综合性指令时，"
    "  才把建网、潮流、过载、电压等一套做完。"
    ""
    "【3. 歧义澄清：只在两条同时满足时反问，否则直接干活】"
    "   1) 问题中无「刚才/之前/这个/继续」等上下文指代词；"
    "   2) 问题中也找不到电网类型（既无 caseXX，也无「9/14/30/39/57/118/300节点」字样）。"
    "   反问：请问您是想基于刚才的电网继续分析，还是想用新模型？新模型请指定节点类型（如30节点）。"
    ""
    "【4. 显式重置】"
    "· 用户说「清空重来/不要之前的电网了/恢复初始」→ 先调 reset_grid_session。"
    ""
    "【5. 多轮与换网】"
    "· 用户说「刚才/之前/继续」→ 复用前面的电网与结果，不必重新 create_test_grid。"
    "· 用户明确说新电网类型（如之前case30，现在说换57节点）→ 调 create_test_grid(新类型) 覆盖即可。"
    ""
    "【6. 输出要求】"
    "· 工具报错时把错误信息清晰告知，不要瞎编。"
    "· 最终回答用简洁中文总结关键数据，禁止原样粘贴大段JSON。"
)

# 服务配置
SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 8000,
    "cors_origins": [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ],
}

# MySQL 业务数据库配置
DATABASE_CONFIG = {
    "mysql_url": "mysql+aiomysql://root:Taylor081930@127.0.0.1:3306/power_agent?charset=utf8",
}