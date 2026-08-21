# -*- coding: utf-8 -*-
"""
大电网静态安全分析智能体

基于pandapower库实现电网分析功能，作为智能体工具供调用
输出格式包含question_id和answer_output两个字段

支持LLM（DeepSeek）智能理解用户问题
"""

import json
import uuid
from typing import Dict, Any, Optional, List
from grid_tools import GridTools
from llm_client import LLMClient
from skills.skill_def import VOLTAGE_CORRECTION_SKILL, LOAD_SWEEP_SKILL

import re

_SKILL_CHECKS = {
    "violations_exist":      lambda state: state.get("viol", {}).get("越限母线数", 0) > 0,
    "correction_succeeded":  lambda state: state.get("corr", {}).get("剩余越限数", -1) == 0,
}


class PowerAgent:
    """大电网静态安全分析智能体
    
    功能：
    1. 使用LLM理解用户问题，智能选择分析工具
    2. 将分析结果格式化输出
    3. 支持多轮对话和问题编号管理
    """
    
    SKIP_RUNPP_TOOLS = {"get_line_overload_summary", "get_voltage_violation_summary", "calculate_loss_analysis"}
    
    def __init__(self, use_llm: bool = True, api_key: str = None):
        """初始化智能体
        
        Args:
            use_llm: 是否启用LLM（默认True）
            api_key: LLM API Key（可选）
        """
        self.grid_tools = GridTools()
        self.llm_client = LLMClient(api_key=api_key) if use_llm else None
        self.question_counter = 0
        self.conversation_history = []
        self.current_grid_type = None
        self._initialized = False
        self._last_used_llm = False
        self._load_sweep_state = {"active": False, "grid_type": None, "scenarios": []}
    
    def get_llm_status(self) -> Dict:
        """获取LLM状态
        
        Returns:
            Dict: LLM状态信息
        """
        if self.llm_client:
            return self.llm_client.get_status()
        return {"configured": False, "reason": "LLM客户端未启用"}
    
    def _generate_question_id(self) -> str:
        """生成问题唯一编号
        
        Returns:
            str: 问题编号
        """
        self.question_counter += 1
        return f"Q{self.question_counter:04d}"
    
    def answer_question(self, question: str, grid_type: str = None,**kwargs) -> Dict[str, Any]:

        question_id = self._generate_question_id()
        
        try:
            # 初始化历史上下文缓存，供 _apply_history_context 和 answer_question 共用
            self._last_pf_check = (False, None)
            
            # 先解析问题，获取推荐的电网类型和工具
            # _apply_history_context 内部会自动修正 grid_type（如需）
            parse_result = self._parse_question(question)
            
            # 历史上下文感知：复用 _apply_history_context 中已检查的结果
            has_recent_pf, pf_grid_type = self._last_pf_check
            
            # 确定电网类型：优先使用用户指定，否则使用解析结果（已由历史上下文修正）
            if grid_type is None:
                grid_type = parse_result.get("grid_type", "case30")
            
            tool_name = parse_result.get("tool_name", "run_ac_power_flow")
            tool_params = parse_result.get("tool_params", {})
            
            can_reuse_pf = (
                has_recent_pf 
                and pf_grid_type == grid_type
                and tool_name in self.SKIP_RUNPP_TOOLS
            )
            
            # 初始化电网（如果需要）
            need_init = (not self._initialized) or (self.current_grid_type != grid_type)
            if need_init:
                init_result = self.grid_tools.create_test_grid(grid_type)
                if not init_result["success"]:
                    return {
                        "question_id": question_id,
                        "answer_output": {
                            "status": "error",
                            "message": f"电网初始化失败: {init_result['message']}",
                        }
                    }
                self._initialized = True
                self.current_grid_type = grid_type
                print(f"[Agent] 已选择电网: {grid_type}")
            elif can_reuse_pf and tool_params.get("skip_runpp"):
                print(f"[Agent] 复用历史潮流结果({grid_type})，跳过重复潮流计算")
            
            # 执行工具（复合分析走专用编排逻辑）
            if tool_name == "_composite_n1_rank":
                result = self._run_composite_n1_rank()
            elif tool_name == "_skill_voltage_correction":
                result = self._run_skill_voltage_correction()
            elif tool_name == "_skill_load_sweep":
                result = self._run_skill_load_sweep()
            elif tool_name == "_skill_load_sweep_step":
                result = self._run_skill_load_sweep_step(question)
                render_tool = result.get("_render_as")
                if render_tool:
                    tool_name = render_tool
                    print(f"[问答式负荷扫描] 重定向渲染工具: {tool_name}")
            else:
                result = self.grid_tools.execute_tool(tool_name, **tool_params)
                if tool_name == "run_ac_power_flow" and self._load_sweep_state.get("active", False):
                    self._load_sweep_state["active"] = False
                    print("[问答式负荷扫描] 检测到非负荷扫描潮流计算，上下文已失效")
            
            # 构建回答
            answer = self._build_answer(question, tool_name, result)
            # 添加电网信息
            answer["grid_type"] = grid_type
            answer["grid_name"] = self._get_grid_display_name(grid_type)
            
            # 记录对话历史
            self.conversation_history.append({
                "question_id": question_id,
                "question": question,
                "grid_type": grid_type,
                "tool_used": tool_name,
                "answer": answer,
            })
            
            return {
                "question_id": question_id,
                "answer_output": answer,
            }
            
        except Exception as e:
            return {
                "question_id": question_id,
                "answer_output": {
                    "status": "error",
                    "message": f"问题处理失败: {str(e)}",
                }
            }
    
    def _get_grid_display_name(self, grid_type: str) -> str:
        """获取电网显示名称
        
        Args:
            grid_type: 电网类型
        
        Returns:
            str: 显示名称
        """
        names = {
            "case9": "IEEE 9节点系统",
            "case14": "IEEE 14节点系统",
            "case30": "IEEE 30节点系统",
            "case39": "IEEE 39节点系统",
            "case57": "IEEE 57节点系统",
            "case118": "IEEE 118节点系统",
            "case300": "IEEE 300节点系统",
            "simple": "自定义简单电网",
        }
        return names.get(grid_type, grid_type)
    
    def _parse_question(self, question: str) -> Dict[str, Any]:
        """解析用户问题，确定电网类型和调用的工具
        优先使用LLM理解，失败时回退到关键词匹配
        复合意图判断在两个分支收敛后统一执行
        历史上下文感知：检测到查询类问题时自动复用之前的潮流计算结果
        
        Args:
            question: 用户问题
        
        Returns:
            Dict: 包含grid_type, tool_name, tool_params的结果
        """
        parse_result = None

        # 分支①: 尝试使用LLM解析
        if self.llm_client and self.llm_client._is_configured():
            try:
                llm_result = self.llm_client.parse_question(question)
                if llm_result and "tool_name" in llm_result:
                    parse_result = {
                        "grid_type": llm_result.get("grid_type", "case30"),
                        "tool_name": llm_result["tool_name"],
                        "tool_params": llm_result.get("tool_params", {}),
                    }
                    self._last_used_llm = True
                    print(f"[LLM] 解析成功: 电网={parse_result['grid_type']}, 工具={parse_result['tool_name']}, 参数={parse_result['tool_params']}")
            except Exception as e:
                print(f"[LLM] 解析失败，回退到关键词匹配: {e}")

        # 分支②: 回退到关键词匹配
        if parse_result is None:
            self._last_used_llm = False
            parse_result = self._parse_by_keywords(question)

        # 历史上下文感知：检测查询类问题是否需要复用潮流结果
        parse_result = self._apply_history_context(parse_result, question)

        # 统一复合意图判断（在两个分支收敛后执行，确保只写一处逻辑）
        if self._is_composite_intent(question):
            if self._is_voltage_correction_skill(question):
                parse_result["tool_name"] = "_skill_voltage_correction"
                parse_result["tool_params"] = {}
                print(f"[skills] 解析成功: 电网={parse_result['grid_type']}, 工具={parse_result['tool_name']}, 参数={parse_result['tool_params']}")
            elif self._is_load_sweep_skill(question):
                parse_result["tool_name"] = "_skill_load_sweep"
                parse_result["tool_params"] = {}
                print(f"[skills] 解析成功: 电网={parse_result['grid_type']}, 工具={parse_result['tool_name']}, 参数={parse_result['tool_params']}")
            else:
                parse_result["tool_name"] = "_composite_n1_rank"
                parse_result["tool_params"] = {}
                print(f"[复合意图] 解析成功: 电网={parse_result['grid_type']}, 工具={parse_result['tool_name']}, 参数={parse_result['tool_params']}")

        if self._is_interactive_load_sweep(question):
            parse_result["tool_name"] = "_skill_load_sweep_step"
            parse_result["tool_params"] = {}
            print(f"[问答式负荷扫描] 解析成功: 电网={parse_result['grid_type']}")

        return parse_result
    
    def _apply_history_context(self, parse_result: Dict, question: str) -> Dict:
        """应用历史会话上下文，检测查询类问题是否需要复用之前的潮流计算结果
        
        当用户在潮流计算后询问"是否出现线路过载"或"是否出现电压越限"时，
        自动检测历史中是否已有潮流计算结果，若有则设置 skip_runpp=True 避免重复计算。
        
        Args:
            parse_result: 初步解析结果
            question: 用户原始问题
        
        Returns:
            Dict: 更新后的解析结果
        """
        tool_name = parse_result.get("tool_name", "")
        tool_params = parse_result.get("tool_params", {})
        
        # 需要潮流结果作为前置条件的工具（但不一定支持 skip_runpp）
        query_tools_need_pf = self.SKIP_RUNPP_TOOLS | {
            "run_n1_security_check",
            "run_short_circuit_analysis",
            "check_voltage_stability",
        }
        
        if tool_name not in query_tools_need_pf:
            return parse_result
        
        # 检查历史记录中是否已有潮流计算结果
        has_recent_pf, pf_grid_type = self._has_recent_power_flow()
        self._last_pf_check = (has_recent_pf, pf_grid_type)
        
        if has_recent_pf:
            # 如果历史中已有潮流结果，且工具支持 skip_runpp，则设置该参数
            if tool_name in self.SKIP_RUNPP_TOOLS:
                if not tool_params.get("skip_runpp", False):
                    tool_params["skip_runpp"] = True
                    parse_result["tool_params"] = tool_params
                    print(f"[历史上下文] 检测到之前的潮流计算结果({pf_grid_type})，跳过重复潮流计算")
            
            # 如果用户没显式指定电网类型（默认case30），且历史潮流的电网类型不同，
            # 则使用历史潮流的电网类型，避免电网被错误重置
            current_grid_type = parse_result.get("grid_type", "")
            if current_grid_type == "case30" and pf_grid_type and pf_grid_type != "case30":
                parse_result["grid_type"] = pf_grid_type
                print(f"[历史上下文] 修正电网类型: {current_grid_type} → {pf_grid_type}")
        
        return parse_result
    
    def _has_recent_power_flow(self) -> tuple:
        """检查历史会话中是否已有潮流计算结果
        
        Returns:
            tuple: (是否存在潮流结果, 电网类型)
        """
        if not self.conversation_history:
            return False, None
        
        # 从最近的历史记录开始查找
        for record in reversed(self.conversation_history):
            answer = record.get("answer", {})
            if answer.get("analysis_type") == "交流潮流计算":
                grid_type = record.get("grid_type", None)
                # 检查潮流结果是否成功
                if answer.get("status") == "success":
                    return True, grid_type
                # 即使失败的潮流也会在 net 中留下结果
                return True, grid_type
        
        return False, None
    
    @staticmethod
    def _is_composite_intent(question: str) -> bool:
        """判断是否为复合任务意图（N-1排序 / 电压修正skill / 负荷扫描skill）。"""
        q = question.lower()
        has_stepwise = any(kw in q for kw in ["逐一", "分别", "逐个", "逐一元件", "逐条", "一条条"])
        has_rank = any(kw in q for kw in ["排序", "风险排序", "严重程度", "排序输出", "排名"])
        has_security = any(kw in q for kw in ["n-1", "n1", "故障", "安全", "扫描", "排查"])
        if has_stepwise and has_rank and has_security:
            return True
        return (PowerAgent._is_voltage_correction_skill(question)
                or PowerAgent._is_load_sweep_skill(question))

    @staticmethod
    def _is_voltage_correction_skill(question: str) -> bool:
        """判断是否触发电压修正skill。
        
        区分"查询电压越限"和"修正电压越限"：
        - 查询类：是否出现电压越限、电压越限情况、电压越限分析
        - 修正类：修正电压越限、修复电压越限、调整电压、消除越限
        """
        q = question.lower()
        triggers = VOLTAGE_CORRECTION_SKILL.get("triggers", [])
        
        # 先检查是否包含触发词
        has_trigger = any(kw in q for kw in triggers)
        if not has_trigger:
            return False
        
        # 排除查询类问题（只查询越限情况，不要求修正）
        query_keywords = ["是否", "情况", "分析", "有哪些", "有没有", "出现", "存在", "显示", "报告"]
        has_query_intent = any(kw in question for kw in query_keywords)
        
        # 如果只是查询越限情况，不触发修正skill
        if has_query_intent and "修正" not in question and "修复" not in question and "调整" not in question and "消除" not in question:
            return False
        
        return True

    @staticmethod
    def _is_load_sweep_skill(question: str) -> bool:
        """判断是否触发负荷扫描skill。"""
        q = question.lower()
        triggers = LOAD_SWEEP_SKILL.get("triggers", [])
        return any(kw in q for kw in triggers)

    def _parse_by_keywords(self, question: str) -> Dict[str, Any]:
        """通过关键词匹配解析问题（备用方案），覆盖扩展工具
        
        Args:
            question: 用户问题
        
        Returns:
            Dict: 包含grid_type, tool_name, tool_params的结果
        """
        question_lower = question.lower()
        
        # 先确定电网类型
        grid_type = self._determine_grid_type(question)
        
        # 再确定工具
        tool_name = "run_ac_power_flow"
        tool_params = {}
        
        # 1. 知识/概念类
        if any(kw in question for kw in ["什么是", "是什么", "电压范围", "正常范围", "n-1检查", "n-1准则",
                                           "有哪些工具", "有哪些分析", "知识", "概念", "怎么算", "什么意思",
                                           "工具一览", "工具总览"]):
            tool_name = "query_knowledge"
            topic = None
            if any(kw in question for kw in ["电压范围", "电压正常", "正常范围"]):
                topic = "voltage_range"
            elif any(kw in question for kw in ["n-1", "n1", "静态安全", "安全校核"]):
                topic = "n1_criteria"
            elif any(kw in question for kw in ["有哪些工具", "工具一览", "工具总览", "有哪些分析"]):
                topic = "tools_overview"
            elif any(kw in question for kw in ["分析方法", "能做哪些", "能做什么"]):
                topic = "analysis_methods"
            elif any(kw in question for kw in ["短路"]):
                topic = "short_circuit"
            elif any(kw in question for kw in ["潮流"]):
                topic = "power_flow"
            elif any(kw in question for kw in ["频率", "基准"]):
                topic = "frequency"
            if topic:
                tool_params = {"topic": topic}
        
        # 2. 拓扑/结构/清单
        elif any(kw in question for kw in ["拓扑", "结构", "连接", "有哪些元件", "电网组成", "组成"]):
            if "母线" in question and "线路" not in question and "发电机" not in question:
                tool_name = "list_grid_elements"
                tool_params = {"element_type": "bus"}
            elif "线路" in question and "母线" not in question:
                tool_name = "list_grid_elements"
                tool_params = {"element_type": "line"}
            elif "发电机" in question and "母线" not in question and "线路" not in question:
                tool_name = "list_grid_elements"
                tool_params = {"element_type": "gen"}
            else:
                tool_name = "get_grid_topology"
        elif any(kw in question for kw in ["列出", "列表", "清单", "所有母线", "所有线路", "所有发电机", "所有变压器"]):
            tool_name = "get_grid_topology"
        
        # 3. 元件参数
        elif any(kw in question for kw in ["参数", "电阻", "电抗", "容量", "额定", "设定值", "阻抗"]):
            et = self._infer_element_type(question)
            if et:
                ref = self._extract_element_ref(question, et)
                tool_name = "get_element_params"
                tool_params = {"element_type": et}
                if ref is not None:
                    tool_params["element_id"] = ref
        
        # 4. 排序筛选 Top-N
        elif any(kw in question for kw in ["最高", "最低", "排序", "前", "top", "最", "最大", "最小", "最重", "最轻"]) and \
             any(kw in question for kw in ["线路", "变压器", "母线", "负载率", "电压", "损耗", "过载"]):
            et, metric, order, top_n = self._infer_rank_params(question)
            tool_name = "rank_elements"
            tool_params = {"element_type": et, "metric": metric, "order": order, "top_n": top_n}
        
        # 5. 单元件 N-1（具体到某元件 + N-1/安全）
        elif any(kw in question for kw in ["n-1", "n1", "安全"]) and self._infer_element_type(question) is not None \
             and self._extract_element_ref(question, self._infer_element_type(question)) is not None:
            et = self._infer_element_type(question)
            ref = self._extract_element_ref(question, et)
            tool_name = "analyze_element_security"
            tool_params = {"element_type": et, "element_id": ref}
        
        # 6. 运行方式（退出/检修/停运 某元件后再分析）
        elif any(kw in question for kw in ["退出", "检修", "停运", "断开", "退出后", "断开后", "检修方式", "运行方式下", "停运后"]) \
             and self._infer_element_type(question) is not None:
            et = self._infer_element_type(question)
            ref = self._extract_element_ref(question, et)
            analysis = "power_flow"
            if any(kw in question for kw in ["越限", "电压"]):
                analysis = "voltage_violation"
            elif any(kw in question for kw in ["过载", "负载率"]):
                analysis = "line_overload"
            ids = [ref] if ref is not None else []
            tool_name = "analyze_with_outage"
            tool_params = {"element_type": et, "element_ids": ids, "analysis": analysis}
        
        # 7. 风险报告（整体风险/证据）
        elif any(kw in question for kw in ["风险报告", "风险", "报告"]) and \
             any(kw in question for kw in ["报告", "风险", "整体", "汇总", "全部", "证据"]):
            tool_name = "generate_risk_report"
        
        # 8. 原有计算类分支
        elif any(kw in question for kw in ["潮流", "潮流计算", "power flow"]):
            tool_name = "run_ac_power_flow"
        
        elif any(kw in question for kw in ["N-1", "n-1", "N1", "安全校核", "静态安全"]):
            element_type = self._infer_element_type(question) or "line"
            tool_name = "run_n1_security_check"
            tool_params = {"element_type": element_type}
        
        elif any(kw in question for kw in ["短路", "short circuit", "故障"]):
            if any(kw in question for kw in ["三相", "3phase", "三相短路"]):
                tool_name = "run_short_circuit_analysis"
                tool_params = {"fault_type": "3phase"}
            elif any(kw in question for kw in ["两相", "2phase"]):
                tool_name = "run_short_circuit_analysis"
                tool_params = {"fault_type": "2phase"}
            elif any(kw in question for kw in ["单相", "1phase", "接地"]):
                tool_name = "run_short_circuit_analysis"
                tool_params = {"fault_type": "1phase"}
            else:
                tool_name = "run_short_circuit_analysis"
                tool_params = {"fault_type": "3phase"}
        
        elif any(kw in question for kw in ["电压稳定", "稳定裕度", "P-V", "pv曲线"]):
            tool_name = "check_voltage_stability"
            tool_params = {"max_load_factor": 2.0}

        elif any(kw in question for kw in [
            "负荷倍率", "负荷扫描", "负荷水平", "负荷调整", "加载分析", "负荷增长",
            "负荷调高", "负荷调到", "调负荷", "加大负荷", "增大负荷", "增加负荷",
            "负荷增加", "负荷放大", "加载", "加负荷", "提负荷", "负荷提升",
        ]):
            tool_name = "_skill_load_sweep"
            tool_params = {}

        elif any(kw in question for kw in ["线路过载", "过载", "负载率", "line loading"]):
            tool_name = "get_line_overload_summary"
            tool_params = {"threshold": 80.0}
        
        elif any(kw in question for kw in ["电压越限", "越限", "电压范围", "violation"]):
            tool_name = "get_voltage_violation_summary"
            tool_params = {"vmin_pu": 0.95, "vmax_pu": 1.05}
        
        elif any(kw in question for kw in ["网损", "损耗", "loss"]):
            tool_name = "calculate_loss_analysis"
        
        elif any(kw in question for kw in ["电网信息", "电网结构", "节点", "母线列表"]):
            tool_name = "create_test_grid"
            tool_params = {"grid_type": grid_type}
        
        return {
            "grid_type": grid_type,
            "tool_name": tool_name,
            "tool_params": tool_params,
        }
    
    def _infer_element_type(self, question: str) -> str:
        """从问题中推断元件类型"""
        if any(kw in question for kw in ["线路", "line"]):
            return "line"
        if any(kw in question for kw in ["母线", "bus", "变电站"]):
            return "bus"
        if any(kw in question for kw in ["变压器", "trafo"]):
            return "trafo"
        if any(kw in question for kw in ["发电机", "generator", "gen"]):
            return "gen"
        if any(kw in question for kw in ["负荷", "load"]):
            return "load"
        return None
    
    def _extract_element_ref(self, question: str, element_type: str):
        """从问题中提取元件引用（编号/名称）"""
        import re
        if element_type == "line":
            m = re.search(r"(\d+)\s*-\s*(\d+)", question)
            if m:
                return f"Line {m.group(1)}-{m.group(2)}"
            m = re.search(r"线路\s*(\d+)", question)
            if m:
                return int(m.group(1))
            m = re.search(r"第\s*(\d+)\s*条", question)
            if m:
                return int(m.group(1))
        else:
            kw = {"bus": "母线", "trafo": "变压器", "gen": "发电机", "load": "负荷"}[element_type]
            m = re.search(kw + r"\s*(\d+)", question)
            if m:
                return int(m.group(1))
            m = re.search(r"第\s*(\d+)\s*(个|座|台)", question)
            if m:
                return int(m.group(1))
        m = re.search(r"(\d+)", question)
        if m:
            return int(m.group(1))
        return None
    
    def _infer_rank_params(self, question: str):
        """推断排序参数：对象、指标、顺序、数量"""
        import re
        if "变压器" in question or "trafo" in question:
            et, metric = "trafo", "loading_percent"
        elif "母线" in question or "bus" in question or "电压" in question:
            et, metric = "bus", "voltage"
        elif "线路" in question or "line" in question:
            et, metric = "line", "loading_percent"
        else:
            et, metric = "line", "loading_percent"
        if "损耗" in question or "线损" in question or "损失" in question:
            metric = "ploss_mw"
        order = "asc" if any(kw in question for kw in ["最低", "最小", "最弱", "最少", "轻"]) else "desc"
        m = re.search(r"(?:前|top|top\s*)(\d+)", question, re.IGNORECASE)
        if m:
            top_n = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s*(?:条|个|座|台)", question)
            top_n = int(m.group(1)) if m else 5
        return et, metric, order, top_n
    
    def _run_composite_n1_rank(self) -> Dict:
        """复合分析：对负载率最高的若干关键线路逐一N-1扫描并按风险排序"""
        try:
            rank = self.grid_tools.rank_elements(
                element_type="line", metric="loading_percent", top_n=5, order="desc"
            )
            if not rank.get("success"):
                return rank
            candidates = [r["ID"] for r in rank.get("排名结果", [])]
            results = []
            for lid in candidates:
                sec = self.grid_tools.analyze_element_security(element_type="line", element_id=lid)
                name = str(lid)
                if self.grid_tools.net is not None and lid in self.grid_tools.net.line.index:
                    name = str(self.grid_tools.net.line.loc[lid, "name"])
                results.append({
                    "线路ID": int(lid),
                    "名称": name,
                    "安全": sec.get("安全"),
                    "潮流收敛": sec.get("潮流收敛"),
                    "电压越限数": sec.get("电压越限数", 0),
                    "过载数": sec.get("过载数", 0),
                })
            results.sort(key=lambda x: (0 if (not x["安全"]) else 1,
                                        -(x["电压越限数"] + x["过载数"])))
            return {
                "success": True,
                "message": "关键线路逐一N-1扫描并按风险排序完成",
                "候选线路(负载率Top5)": candidates,
                "逐一分析结果": results,
                "说明": "按风险严重程度排序：不安全(存在越限/过载)的线路排在前面",
            }
        except Exception as e:
            return {"success": False, "message": f"复合分析失败: {str(e)}"}
    
    def _execute_skill(self, skill_def: Dict) -> Dict:
        """通用Skill执行引擎

        解释skill_def中的steps，动态编排grid_tools工具调用。
        支持 tool / check / loop / end 四种step类型。
        tool步骤支持可选 params 参数（Dict），透传给 execute_tool。

        Args:
            skill_def: Skill定义字典（含steps, max_iterations等）

        Returns:
            Dict: 执行结果，包含：
                - success: 是否成功
                - 迭代日志: loop类迭代的记录
                - 最终状态: 所有save_key的结果字典
                - skill: skill名称
                - message: 执行消息
        """
        steps = skill_def.get("steps", [])
        max_iterations = skill_def.get("max_iterations", 10)
        no_improve_limit = skill_def.get("no_improve_limit", 3)
        skill_name = skill_def.get("name", "unknown")

        state = {}
        iteration_log = []

        iteration = 0
        step_idx = 0
        forced_end = False

        while step_idx < len(steps):
            step = steps[step_idx]
            action = step.get("action")

            if action == "tool":
                tool_name = step["tool"]
                save_key = step.get("save")
                params = step.get("params", {})
                tolerant = step.get("tolerant", False)
                result = self.grid_tools.execute_tool(tool_name, **params)

                if save_key:
                    state[save_key] = result

                if not result.get("success"):
                    if tolerant:
                        step_idx += 1
                        continue
                    return {
                        "success": False,
                        "message": f"Skill [{skill_name}] 第{iteration + 1}次迭代：工具 {tool_name} 执行失败 - {result.get('message')}",
                        "迭代日志": iteration_log,
                        "skill": skill_name,
                    }

                step_idx += 1

            elif action == "check":
                check_name = step["check"]
                check_fn = _SKILL_CHECKS.get(check_name)
                condition_met = check_fn(state) if check_fn else False

                branch = step.get("then" if condition_met else "else", {"action": "end"})
                branch_action = branch.get("action", "end")

                if branch_action == "tool":
                    tool_name = branch["tool"]
                    save_key = branch.get("save")
                    params = branch.get("params", {})
                    result = self.grid_tools.execute_tool(tool_name, **params)

                    if save_key:
                        state[save_key] = result

                    if not result.get("success"):
                        if tolerant:
                            step_idx += 1
                            continue
                        return {
                            "success": False,
                            "message": f"Skill [{skill_name}] 第{iteration + 1}次迭代：分支工具 {tool_name} 执行失败 - {result.get('message')}",
                            "迭代日志": iteration_log,
                            "skill": skill_name,
                        }

                    step_idx += 1

                elif branch_action == "loop":
                    step_idx = 0
                    iteration += 1
                    if iteration >= max_iterations:
                        forced_end = True
                        break

                elif branch_action == "end":
                    forced_end = True
                    break

                else:
                    step_idx += 1

            elif action == "loop":
                step_idx = 0
                iteration += 1
                if iteration >= max_iterations:
                    forced_end = True
                    break

            elif action == "end":
                forced_end = True
                break

            else:
                step_idx += 1

        return {
            "success": True,
            "message": f"Skill [{skill_name}] 执行完成，共迭代{len(iteration_log)}次",
            "迭代日志": iteration_log,
            "最终状态": state,
            "skill": skill_name,
        }

    def _run_skill_voltage_correction(self) -> Dict:
        """Skill编排：潮流计算 → 电压越限检测 → 修正 → 重跑

        实际执行逻辑由 _execute_skill(VOLTAGE_CORRECTION_SKILL) 解释运行，
        此方法负责从引擎返回的 state 中提取电压修正相关数据，组装最终结果。
        """
        try:
            result = self._execute_skill(VOLTAGE_CORRECTION_SKILL)

            if not result.get("success"):
                return result

            state = result.get("最终状态", {})
            iteration_log = result.get("迭代日志", [])

            pf = state.get("pf", {})
            viol = state.get("viol", {})
            corr = state.get("corr", {})

            final_count = viol.get("越限母线数", 0)
            converged = final_count == 0

            msg = f"电压修正Skill完成，共迭代{len(iteration_log)}次"
            if converged:
                msg += "，电压已全部合格"
            else:
                msg += f"，最终越限数{final_count}"

            result["message"] = msg
            result["收敛"] = converged
            result["最终潮流"] = pf
            result["最终越限"] = viol
            result["最终修正"] = corr
            return result
        except Exception as e:
            return {"success": False, "message": f"电压修正skill执行失败: {str(e)}"}

    def _run_skill_load_sweep(self) -> Dict:
        """Skill编排：负荷倍率递增 → 潮流计算 → 线路过载检测

        实际执行逻辑由 _execute_skill(LOAD_SWEEP_SKILL) 解释运行，
        此方法负责从引擎返回的 state 中提取各倍率场景的过载数据，组装最终结果。
        """
        try:
            result = self._execute_skill(LOAD_SWEEP_SKILL)

            if not result.get("success"):
                return result

            state = result.get("最终状态", {})

            scenario_log = []
            for key, val in sorted(state.items()):
                if key.startswith("overload_"):
                    suffix = key.split("_")[-1]
                    scale_info = state.get(f"scale_{suffix}", {})
                    pf_info = state.get(f"pf_{suffix}", {})

                    converged = pf_info.get("success", False)
                    scenario_log.append({
                        "场景": len(scenario_log) + 1,
                        "倍率": scale_info.get("倍率", 0),
                        "潮流收敛": converged,
                        "总线路数": val.get("总线路数", 0),
                        "过载线路数": val.get("过载线路数", 0),
                        "过载详情": val.get("过载线路详情", []),
                        "错误信息": "" if converged else pf_info.get("message", ""),
                    })

            overload_details = []
            for scenario in scenario_log:
                overload_details.append({
                    "倍率": scenario.get("倍率", 0),
                    "总线路数": scenario.get("总线路数", 0),
                    "过载线路数": scenario.get("过载线路数", 0),
                    "过载线路": scenario.get("过载详情", []),
                })

            msg = f"负荷扫描Skill完成，共分析 {len(scenario_log)} 个场景"
            for sd, sc in zip(overload_details, scenario_log):
                has_overload = sd["过载线路数"] > 0
                converged = sc.get("潮流收敛", True)
                if not converged:
                    msg += f"；{sd['倍率']}倍时潮流不收敛（{sc.get('错误信息', '')[:60]}）"
                else:
                    msg += f"；{sd['倍率']}倍时{'出现' if has_overload else '无'}线路过载（{sd['过载线路数']}条）"

            result["message"] = msg
            result["场景日志"] = scenario_log
            result["负荷扫描结果"] = overload_details
            return result
        except Exception as e:
            return {"success": False, "message": f"负荷扫描skill执行失败: {str(e)}"}

    @staticmethod
    def _extract_load_factor(question: str) -> Optional[float]:
        """从问题中提取负荷倍率数值

        支持的格式:
        - "2倍", "2 倍", "2.0倍", "2x", "两倍", "二倍"
        - "调高2倍", "调到2倍", "2倍水平"

        当问题包含多倍率对比模式时返回None（如"对比2倍和4倍"）。

        Args:
            question: 用户问题

        Returns:
            Optional[float]: 倍率值，未找到或多倍率对比返回None
        """
        import re
        q = question.strip()

        comparison_kw = ["对比", "比较", "和", "与", "跟", "及", "versus", "vs"]
        if any(kw in q for kw in comparison_kw) and len(re.findall(r'[\d]+\.?[\d]*\s*[倍xX]', q)) >= 2:
            return None

        ch_map = {"一": 1.0, "二": 2.0, "两": 2.0, "三": 3.0, "四": 4.0,
                  "五": 5.0, "六": 6.0, "七": 7.0, "八": 8.0, "九": 9.0, "十": 10.0}

        m = re.search(r'(\d+\.?\d*)\s*[倍xX]', q)
        if m:
            return float(m.group(1))

        for ch, val in sorted(ch_map.items(), key=lambda x: -len(x[0])):
            pattern = ch + r'\s*[倍xX]'
            if re.search(pattern, q):
                return val

        m = re.search(r'(\d+\.?\d*)', q)
        if m and any(kw in q for kw in ["倍", "倍率", "水平", "负荷"]):
            return float(m.group(1))

        return None

    def _is_interactive_load_sweep(self, question: str) -> bool:
        """判断是否为问答式负荷扫描模式

        判定逻辑:
        1. 已激活状态下，用户继续追问负荷相关结果（即使不含"负荷"关键词）
        2. 用户问题中包含负荷相关关键词 + 具体倍率
        3. 排除纯批处理请求

        Args:
            question: 用户问题

        Returns:
            bool: 是否进入问答式编排模式
        """
        q = question.lower()
        load_keywords = ["负荷", "加载", "倍率", "倍", "水平", "调高", "调大",
                         "加大", "增大", "增加", "提升", "放大", "提负荷", "加负荷"]
        has_load_kw = any(kw in q for kw in load_keywords)

        batch_keywords = ["扫描", "全扫", "全部倍率", "所有倍率", "批量"]
        is_batch = any(kw in question for kw in batch_keywords)

        if self._load_sweep_state.get("active", False):
            if is_batch:
                return False
            query_kw = ["对比", "比较", "结果", "情况", "有哪些", "出现", "存在",
                        "过载", "概况", "怎么样", "如何", "多少"]
            if has_load_kw or any(kw in q for kw in query_kw):
                return True

        if not has_load_kw:
            return False

        if is_batch:
            return False

        factor = self._extract_load_factor(question)
        if factor is not None:
            return True

        return False

    def _load_sweep_extract_from_history(self) -> Dict:
        """从会话历史中提取问答式负荷扫描的已有状态

        Returns:
            Dict: 包含已完成的场景列表和上下文信息
        """
        scenarios = list(self._load_sweep_state.get("scenarios", []))
        grid_type = self._load_sweep_state.get("grid_type")

        for record in self.conversation_history:
            answer = record.get("answer", {})
            analysis_type = answer.get("analysis_type", "")
            if analysis_type in ("负荷扫描Skill", "问答式负荷扫描"):
                data = answer.get("data", [])
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "倍率" in item:
                            found = False
                            for s in scenarios:
                                if s.get("倍率") == item.get("倍率"):
                                    found = True
                                    break
                            if not found:
                                scenarios.append(item)

        scenarios.sort(key=lambda x: x.get("倍率", 0))
        return {"scenarios": scenarios, "grid_type": grid_type}

    @staticmethod
    def _detect_load_sweep_intent(question: str) -> Dict:
        """检测问答式负荷扫描的用户意图

        Returns:
            Dict: {
                "want_pf": bool,       是否需要潮流计算结果
                "want_overload": bool, 是否需要线路过载分析
                "want_compare": bool, 是否需要多倍率对比
                "want_details": bool, 是否需要详细数据
            }
        """
        q = question.lower()

        want_pf = any(kw in q for kw in ["潮流计算", "潮流", "电压", "母线", "功率",
                                          "电流", "损耗", "发电机", "输出"])
        want_overload = any(kw in q for kw in ["过载", "过负荷", "重载", "线路过载",
                                                "overload", "拥塞"])
        want_compare = any(kw in q for kw in ["对比", "比较", "差异", "区别"])

        if not want_pf and not want_overload:
            want_pf = True
            want_overload = True

        return {
            "want_pf": want_pf,
            "want_overload": want_overload,
            "want_compare": want_compare,
        }

    def _run_skill_load_sweep_step(self, question: str) -> Dict:
        """问答式负荷扫描编排方法

        根据用户意图返回对应工具的标准结果格式:
        - 纯潮流意图 → run_ac_power_flow 原始格式
        - 纯过载意图 → get_line_overload_summary 原始格式
        - 混合/查询/对比意图 → 问答式组合格式

        Args:
            question: 用户问题

        Returns:
            Dict: 执行结果，含 _render_as 标记用于外部格式路由
        """
        need_restore = False
        try:
            intent = self._detect_load_sweep_intent(question)
            factor = self._extract_load_factor(question)

            existing = self._load_sweep_extract_from_history()
            scenarios = existing["scenarios"]
            grid_type = existing["grid_type"]

            self._load_sweep_state["active"] = True
            if grid_type is None:
                grid_type = self.current_grid_type or "case30"
            self._load_sweep_state["grid_type"] = grid_type

            if factor is not None:
                already_done = [s for s in scenarios if s.get("倍率") == factor]
                pf_converged = True

                if already_done and not (intent["want_pf"] ^ intent["want_overload"]):
                    print(f"[问答式负荷扫描] {factor}倍场景已存在")
                    if not already_done[0].get("潮流收敛", True):
                        pf_converged = False
                else:
                    if already_done:
                        print(f"[问答式负荷扫描] {factor}倍场景已存在，重新获取原始结果")
                    else:
                        print(f"[问答式负荷扫描] 执行 {factor} 倍场景计算")

                    scale_result = self.grid_tools.execute_tool("set_load_scale", factor=factor)
                    if not scale_result.get("success"):
                        return {"success": False, "message": f"设置负荷倍率失败: {scale_result.get('message')}"}

                    need_restore = True

                    pf_result = self.grid_tools.execute_tool("run_ac_power_flow")
                    pf_converged = pf_result.get("success", False)

                    scenario = {
                        "倍率": factor,
                        "潮流收敛": pf_converged,
                    }

                    if pf_converged:
                        if intent["want_overload"]:
                            overload_result = self.grid_tools.execute_tool(
                                "get_line_overload_summary", skip_runpp=True
                            )
                            scenario["总线路数"] = overload_result.get("总线路数", 0)
                            scenario["过载线路数"] = overload_result.get("过载线路数", 0)
                            scenario["过载线路"] = overload_result.get("过载线路详情", [])

                        if intent["want_pf"]:
                            scenario["母线电压"] = pf_result.get("母线电压", [])
                            scenario["线路潮流"] = pf_result.get("线路潮流", [])
                            scenario["综合指标"] = pf_result.get("综合指标", {})
                            scenario["发电机输出"] = pf_result.get("发电机输出", [])
                            scenario["负载功率"] = pf_result.get("负载功率", [])

                        print(f"[问答式负荷扫描] 完成 {factor} 倍计算")
                    else:
                        scenario["错误信息"] = pf_result.get("message", "")
                        print(f"[问答式负荷扫描] {factor}倍潮流不收敛")

                    scenarios = [s for s in scenarios if s.get("倍率") != factor]
                    scenarios.append(scenario)
                    self._load_sweep_state["scenarios"] = scenarios

                if pf_converged:
                    if intent["want_pf"] and not intent["want_overload"]:
                        pf_result["_render_as"] = "run_ac_power_flow"
                        pf_result["_load_factor"] = factor
                        return pf_result
                    elif intent["want_overload"] and not intent["want_pf"]:
                        overload_result = self.grid_tools.execute_tool(
                            "get_line_overload_summary", skip_runpp=True
                        )
                        overload_result["_render_as"] = "get_line_overload_summary"
                        overload_result["_load_factor"] = factor
                        return overload_result

                current_scenarios = [s for s in scenarios if s.get("倍率") == factor]
                result = self._assemble_interactive_result(current_scenarios, question, intent, factor=factor)
                return result

            else:
                print("[问答式负荷扫描] 查询模式")

                if scenarios:
                    latest = scenarios[-1]
                    latest_factor = latest.get("倍率", 1.0)
                    print(f"[问答式负荷扫描] 使用历史场景: {latest_factor}倍")

                    if not latest.get("潮流收敛", True):
                        result = self._assemble_interactive_result([latest], question, intent, factor=latest_factor)
                        return result

                    if intent["want_overload"] and not intent["want_pf"]:
                        result = {
                            "success": True,
                            "总线路数": latest.get("总线路数", 0),
                            "过载线路数": latest.get("过载线路数", 0),
                            "过载线路详情": latest.get("过载线路", []),
                            "_render_as": "get_line_overload_summary",
                            "_load_factor": latest_factor,
                        }
                        return result

                    if intent["want_pf"] and not intent["want_overload"]:
                        result = {
                            "success": True,
                            "母线电压": latest.get("母线电压", []),
                            "线路潮流": latest.get("线路潮流", []),
                            "综合指标": latest.get("综合指标", {}),
                            "发电机输出": latest.get("发电机输出", []),
                            "负载功率": latest.get("负载功率", []),
                            "_render_as": "run_ac_power_flow",
                            "_load_factor": latest_factor,
                        }
                        return result

                    result = self._assemble_interactive_result([latest], question, intent, factor=latest_factor)
                    return result

                elif intent["want_pf"] or intent["want_overload"]:
                    print("[问答式负荷扫描] 无历史场景，基于当前电网状态执行潮流计算")

                    pf_result = self.grid_tools.execute_tool("run_ac_power_flow")
                    pf_converged = pf_result.get("success", False)

                    if pf_converged:
                        if intent["want_overload"] and not intent["want_pf"]:
                            overload_result = self.grid_tools.execute_tool(
                                "get_line_overload_summary", skip_runpp=True
                            )
                            overload_result["_render_as"] = "get_line_overload_summary"
                            overload_result["_load_factor"] = 1.0
                            return overload_result

                        if intent["want_pf"] and not intent["want_overload"]:
                            pf_result["_render_as"] = "run_ac_power_flow"
                            pf_result["_load_factor"] = 1.0
                            return pf_result

                        overload_result = self.grid_tools.execute_tool(
                            "get_line_overload_summary", skip_runpp=True
                        )
                        current_scenario = {
                            "倍率": 1.0,
                            "潮流收敛": True,
                            "总线路数": overload_result.get("总线路数", 0),
                            "过载线路数": overload_result.get("过载线路数", 0),
                            "过载线路": overload_result.get("过载线路详情", []),
                            "母线电压": pf_result.get("母线电压", []),
                            "线路潮流": pf_result.get("线路潮流", []),
                            "综合指标": pf_result.get("综合指标", {}),
                            "发电机输出": pf_result.get("发电机输出", []),
                            "负载功率": pf_result.get("负载功率", []),
                        }
                        scenarios = [current_scenario]
                    else:
                        print("[问答式负荷扫描] 潮流不收敛")
                        scenarios = [{
                            "倍率": 1.0,
                            "潮流收敛": False,
                            "错误信息": pf_result.get("message", ""),
                        }]

                    result = self._assemble_interactive_result(scenarios, question, intent)
                    return result

            result = self._assemble_interactive_result(scenarios, question, intent)
            return result

        except Exception as e:
            return {"success": False, "message": f"问答式负荷扫描执行失败: {str(e)}"}
        finally:
            if need_restore:
                try:
                    self.grid_tools.execute_tool("set_load_scale", factor=1.0)
                    print("[问答式负荷扫描] 恢复负荷倍率至1.0")
                except Exception as e:
                    print(f"[问答式负荷扫描] 恢复负荷倍率失败: {e}")

    def _assemble_interactive_result(self, scenarios: list, question: str, intent: Dict, factor: Optional[float] = None) -> Dict:
        """组装问答式负荷扫描的最终结果（混合/查询/对比场景）

        Args:
            scenarios: 已完成的场景列表
            question: 用户原始问题
            intent: 用户意图检测结果
            factor: 当前操作的倍率（None表示展示全部）

        Returns:
            Dict: 格式化的结果
        """
        if not scenarios:
            return {"success": True, "message": "暂无负荷扫描数据", "场景日志": []}

        msg_parts = []
        display_scenarios = []

        for s in scenarios:
            display_item = {"倍率": s.get("倍率", 0), "潮流收敛": s.get("潮流收敛", True)}

            if not s.get("潮流收敛", True):
                msg_parts.append(f"{s['倍率']}倍时潮流不收敛")
                display_item["错误信息"] = s.get("错误信息", "")
            else:
                overload_count = s.get("过载线路数", 0)
                display_item["过载线路数"] = overload_count
                display_item["总线路数"] = s.get("总线路数", 0)
                display_item["过载线路"] = s.get("过载线路", [])

                if intent["want_pf"]:
                    display_item["综合指标"] = s.get("综合指标", {})
                    display_item["母线电压"] = s.get("母线电压", [])
                    display_item["线路潮流"] = s.get("线路潮流", [])
                    display_item["发电机输出"] = s.get("发电机输出", [])
                    display_item["负载功率"] = s.get("负载功率", [])

                if intent["want_overload"] and not intent["want_pf"]:
                    msg_parts.append(
                        f"{s['倍率']}倍时{'出现' if overload_count > 0 else '无'}线路过载（{overload_count}条）"
                    )
                elif intent["want_pf"]:
                    metrics = s.get("综合指标", {})
                    loss = metrics.get("总有功损耗_MW", 0) if metrics else 0
                    msg_parts.append(f"{s['倍率']}倍潮流收敛，有功损耗{loss:.2f}MW，过载{overload_count}条")
                else:
                    msg_parts.append(f"{s['倍率']}倍时过载{overload_count}条")

            display_scenarios.append(display_item)

        if factor is not None:
            msg = f"{factor}倍负荷调整后：{'；'.join(msg_parts)}"
        else:
            msg = f"负荷扫描结果：{'；'.join(msg_parts)}"

        return {
            "success": True,
            "message": msg,
            "场景日志": display_scenarios,
            "负荷扫描结果": display_scenarios,
        }

    def _determine_grid_type(self, question: str) -> str:
        """根据问题关键词确定推荐的电网类型
        
        Args:
            question: 用户问题
        
        Returns:
            str: 推荐的电网类型
        """
        # 用户明确指定
        if any(kw in question for kw in ["9节点", "case9", "简单", "入门"]):
            return "case9"
        if any(kw in question for kw in ["14节点", "case14"]):
            return "case14"
        if any(kw in question for kw in ["30节点", "case30", "标准", "常用"]):
            return "case30"
        if any(kw in question for kw in ["39节点", "case39", "新英格兰", "New England"]):
            return "case39"
        if any(kw in question for kw in ["57节点", "case57", "中型"]):
            return "case57"
        if any(kw in question for kw in ["118节点", "case118", "大型", "复杂"]):
            return "case118"
        if any(kw in question for kw in ["300节点", "case300", "超大"]):
            return "case300"
        if any(kw in question for kw in ["自定义", "simple", "简单电网"]):
            return "simple"
        
        # 根据任务类型推荐
        # N-1校核、短路分析等复杂任务推荐较大电网
        if any(kw in question for kw in ["N-1", "n-1", "N1", "短路", "故障", "静态安全"]):
            return "case39"
        
        # 电压稳定分析推荐中型以上电网
        if any(kw in question for kw in ["电压稳定", "稳定裕度", "P-V"]):
            return "case57"
        
        # 潮流计算等默认用case30
        return "case30"
    
    def _build_answer(self, question: str, tool_name: str, 
                      result: Dict) -> Dict[str, Any]:
        """构建回答输出
        
        Args:
            question: 用户问题
            tool_name: 使用的工具名称
            result: 工具执行结果
        
        Returns:
            Dict[str, Any]: 格式化的回答
        """
        answer = {
            "status": "success" if result.get("success", False) else "failed",
            "question": question,
            "analysis_type": self._get_analysis_type_name(tool_name),
            "message": result.get("message", ""),
            "data": self._format_result_data(tool_name, result),
            "summary": self._generate_summary(tool_name, result),
        }

        result.pop("_render_as", None)
        result.pop("_load_factor", None)

        return answer
    
    def _get_analysis_type_name(self, tool_name: str) -> str:
        """获取分析类型中文名
        
        Args:
            tool_name: 工具名称
        
        Returns:
            str: 中文类型名
        """
        type_map = {
            "create_test_grid": "电网建模",
            "run_ac_power_flow": "交流潮流计算",
            "run_n1_security_check": "N-1静态安全校核",
            "run_short_circuit_analysis": "短路计算分析",
            "check_voltage_stability": "电压稳定性分析",
            "get_line_overload_summary": "线路过载分析",
            "get_voltage_violation_summary": "电压越限分析",
            "calculate_loss_analysis": "网损分析",
            "get_grid_topology": "电网拓扑查询",
            "list_grid_elements": "元件清单查询",
            "get_element_params": "元件参数查询",
            "query_knowledge": "知识/元信息查询",
            "rank_elements": "元件排序筛选",
            "analyze_element_security": "单元件N-1安全分析",
            "generate_risk_report": "电网风险报告",
            "analyze_with_outage": "运行方式分析",
            "_composite_n1_rank": "关键线路N-1复合分析",
            "_skill_voltage_correction": "电压修正Skill",
            "_skill_load_sweep": "负荷扫描Skill",
            "_skill_load_sweep_step": "问答式负荷扫描",
        }
        return type_map.get(tool_name, tool_name)
    
    def _format_result_data(self, tool_name: str, result: Dict) -> Any:
        """格式化结果数据
        
        Args:
            tool_name: 工具名称
            result: 原始结果
        
        Returns:
            Any: 格式化后的数据
        """
        if tool_name == "run_ac_power_flow":
            return {
                "综合指标": result.get("综合指标", {}),
                "线路潮流": result.get("线路潮流", [])[:5],
                "母线电压": result.get("母线电压", [])[:5],
                "发电机输出": result.get("发电机输出", []),
            }
        elif tool_name == "run_n1_security_check":
            return {
                "统计信息": result.get("统计信息", {}),
                "部分详细结果": result.get("详细结果", [])[:10],
            }
        elif tool_name == "run_short_circuit_analysis":
            return {
                "短路类型": result.get("短路类型", ""),
                "母线短路结果": result.get("母线短路结果", [])[:5],
            }
        elif tool_name == "check_voltage_stability":
            return {
                "稳定裕度": result.get("稳定裕度(%)", 0),
                "说明": result.get("说明", ""),
                "P-V曲线数据": result.get("P-V曲线数据", [])[:5],
            }
        elif tool_name == "get_line_overload_summary":
            return {
                "统计": {
                    "总线路数": result.get("总线路数", 0),
                    "过载线路数": result.get("过载线路数", 0),
                },
                "过载线路": result.get("过载线路详情", [])[:5],
                "负载率统计": result.get("线路负载率统计", {}),
            }
        elif tool_name == "get_voltage_violation_summary":
            return {
                "统计": {
                    "总母线数": result.get("总母线数", 0),
                    "越限母线数": result.get("越限母线数", 0),
                },
                "越限母线": result.get("越限母线详情", [])[:5],
                "电压统计": result.get("电压统计", {}),
            }
        elif tool_name == "calculate_loss_analysis":
            return {
                "总供电功率(MW)": result.get("总供电功率(MW)", 0),
                "总有功损耗(MW)": result.get("总有功损耗(MW)", 0),
                "网损率(%)": result.get("网损率(%)", 0),
            }
        elif tool_name == "create_test_grid":
            return result.get("grid_info", {})
        elif tool_name == "get_grid_topology":
            return {
                "电网规模": result.get("电网规模", {}),
                "母线列表": result.get("母线列表", [])[:10],
                "线路连接": result.get("线路连接", [])[:10],
                "发电机列表": result.get("发电机列表", [])[:10],
                "说明": "仅展示前10条，完整数据见原始结果",
            }
        elif tool_name == "list_grid_elements":
            return {"元件列表": result.get("元件列表", {})}
        elif tool_name == "get_element_params":
            return result.get("参数", {})
        elif tool_name == "query_knowledge":
            data = {}
            if result.get("知识条目"):
                data["知识条目"] = result["知识条目"]
            if result.get("可用工具"):
                data["可用工具"] = result["可用工具"]
            if result.get("提示"):
                data["提示"] = result["提示"]
            if not data:
                data = {"message": result.get("message", "")}
            return data
        elif tool_name == "rank_elements":
            return {
                "排序对象": result.get("排序对象", ""),
                "指标": result.get("指标", ""),
                "顺序": result.get("顺序", ""),
                "排名结果": result.get("排名结果", []),
            }
        elif tool_name == "analyze_element_security":
            return {
                "故障元件": result.get("故障元件", ""),
                "潮流收敛": result.get("潮流收敛", False),
                "安全": result.get("安全", False),
                "电压越限数": result.get("电压越限数", 0),
                "过载数": result.get("过载数", 0),
                "电压越限证据": result.get("电压越限证据", []),
                "过载证据": result.get("过载证据", []),
            }
        elif tool_name == "generate_risk_report":
            return {
                "风险等级": result.get("风险等级", ""),
                "风险总数": result.get("风险总数", 0),
                "电压越限数": result.get("电压越限数", 0),
                "线路过载数": result.get("线路过载数", 0),
                "变压器过载数": result.get("变压器过载数", 0),
                "风险明细": result.get("风险明细(前5)", []),
                "运行建议": result.get("运行建议", ""),
            }
        elif tool_name == "analyze_with_outage":
            return {
                "退出元件": result.get("退出元件", []),
                "分析类型": result.get("分析类型", ""),
                "综合指标": result.get("综合指标", {}),
                "越限母线": result.get("越限母线", []),
                "过载线路": result.get("过载线路", []),
            }
        elif tool_name == "_composite_n1_rank":
            return {
                "候选线路": result.get("候选线路(负载率Top5)", []),
                "逐一分析结果": result.get("逐一分析结果", []),
                "说明": result.get("说明", ""),
            }
        elif tool_name == "_skill_voltage_correction":
            return {
                "收敛": result.get("收敛", False),
                "迭代日志": result.get("迭代日志", []),
                "最终越限": result.get("最终越限", {}),
                "最终潮流": result.get("最终潮流", {}),
            }
        elif tool_name == "_skill_load_sweep":
            return result.get("负荷扫描结果", [])
        elif tool_name == "_skill_load_sweep_step":
            return result.get("负荷扫描结果", [])
        else:
            return result
    
    def _generate_summary(self, tool_name: str, result: Dict) -> str:
        """生成分析摘要
        
        Args:
            tool_name: 工具名称
            result: 结果数据
        
        Returns:
            str: 摘要文本
        """
        if not result.get("success", False):
            return f"分析失败：{result.get('message', '未知错误')}"
        
        summaries = []
        
        if tool_name == "run_ac_power_flow":
            metrics = result.get("综合指标", {})
            load_factor = result.get("_load_factor")
            prefix = f"{load_factor}倍负荷调整后，" if load_factor else ""
            summaries.append(f"{prefix}潮流计算完成")
            if "平均电压(pu)" in metrics:
                summaries.append(f"平均电压 {metrics['平均电压(pu)']:.4f} pu")
            if "线路最大负载率(%)" in metrics:
                summaries.append(f"线路最大负载率 {metrics['线路最大负载率(%)']:.2f}%")
            if "总有功损耗(MW)" in metrics:
                summaries.append(f"总有功损耗 {metrics['总有功损耗(MW)']:.4f} MW")
            
        elif tool_name == "run_n1_security_check":
            stats = result.get("统计信息", {})
            summaries.append(f"N-1校核完成，安全性评级：{stats.get('安全性评级', '未知')}")
            summaries.append(f"共校核 {stats.get('元件总数', 0)} 个元件")
            summaries.append(f"电压越限 {stats.get('电压越限次数', 0)} 次")
            summaries.append(f"线路过载 {stats.get('线路过载次数', 0)} 次")
            
        elif tool_name == "run_short_circuit_analysis":
            summaries.append(f"短路计算完成({result.get('短路类型', '')})")
            
        elif tool_name == "check_voltage_stability":
            summaries.append(
                f"电压稳定裕度 {result.get('稳定裕度(%)', 0):.1f}%"
            )
            summaries.append(result.get("说明", ""))
            
        elif tool_name == "get_line_overload_summary":
            load_factor = result.get("_load_factor")
            prefix = f"{load_factor}倍负荷调整后，" if load_factor else ""
            summaries.append(
                f"{prefix}线路过载分析：{result.get('过载线路数', 0)}/{result.get('总线路数', 0)} 条线路过载"
            )
            
        elif tool_name == "get_voltage_violation_summary":
            summaries.append(
                f"电压越限分析：{result.get('越限母线数', 0)}/{result.get('总母线数', 0)} 个母线电压越限"
            )
            
        elif tool_name == "calculate_loss_analysis":
            summaries.append(f"网损率 {result.get('网损率(%)', 0):.4f}%")
            summaries.append(f"总有功损耗 {result.get('总有功损耗(MW)', 0):.4f} MW")

        elif tool_name == "get_grid_topology":
            scale = result.get("电网规模", {})
            summaries.append(
                f"电网含 {scale.get('母线数', 0)} 母线、{scale.get('线路数', 0)} 线路、"
                f"{scale.get('变压器数', 0)} 变压器、{scale.get('发电机数', 0)} 发电机"
            )

        elif tool_name == "list_grid_elements":
            items = result.get("元件列表", {})
            parts = [f"{k}:{len(v)}个" for k, v in items.items()]
            summaries.append("元件清单 - " + "，".join(parts))

        elif tool_name == "get_element_params":
            p = result.get("参数", {})
            conn = ""
            if "起始母线" in p and "终止母线" in p:
                conn = f"，连接 {p['起始母线']} ↔ {p['终止母线']}"
            elif "高压侧母线" in p and "低压侧母线" in p:
                conn = f"，高/低压侧为 {p['高压侧母线']} ↔ {p['低压侧母线']}"
            elif "所在母线" in p:
                conn = f"，位于 {p['所在母线']}"
            summaries.append(f"{p.get('名称', '')} 参数已获取{conn}")

        elif tool_name == "query_knowledge":
            entries = result.get("知识条目", [])
            if entries:
                # 标题 + 内容要点，确保把关键数值/结论带回自然语言摘要
                first = entries[0]
                summaries.append(f"知识：{first.get('title', '')}——{first.get('content', '')}")
                for e in entries[1:]:
                    summaries.append(f"{e.get('title', '')}：{e.get('content', '')}")
            else:
                summaries.append("未匹配到相关知识")

        elif tool_name == "rank_elements":
            top = result.get("排名结果", [])
            if top:
                t0 = top[0]
                summaries.append(
                    f"{result.get('排序对象','')}按{result.get('指标','')}排序："
                    f"第1为 {t0.get('名称','')} ({t0.get('指标值','')}{t0.get('单位','')})"
                )
            else:
                summaries.append("无排序结果")

        elif tool_name == "analyze_element_security":
            if result.get("安全"):
                summaries.append(f"{result.get('故障元件','')} 开断后系统安全")
            else:
                summaries.append(
                    f"{result.get('故障元件','')} 开断后存在风险："
                    f"电压越限 {result.get('电压越限数',0)} 处，过载 {result.get('过载数',0)} 处"
                )

        elif tool_name == "generate_risk_report":
            summaries.append(
                f"风险等级：{result.get('风险等级','')}，共 {result.get('风险总数',0)} 项风险"
                f"（电压越限 {result.get('电压越限数',0)}、线路过载 {result.get('线路过载数',0)}）"
            )

        elif tool_name == "analyze_with_outage":
            summaries.append(
                f"已退出 {','.join(result.get('退出元件', []))} 的运行方式下"
                f"{result.get('分析类型','')}分析完成"
            )

        elif tool_name == "_composite_n1_rank":
            results = result.get("逐一分析结果", [])
            unsafe = [r for r in results if not r.get("安全")]
            summaries.append(
                f"关键线路Top5逐一N-1完成，其中 {len(unsafe)} 条开断后不安全"
            )

        elif tool_name == "_skill_voltage_correction":
            converged = result.get("收敛", False)
            log = result.get("迭代日志", [])
            summaries.append(
                f"电压修正Skill：共迭代{len(log)}次，{'已收敛' if converged else '未收敛'}"
                f"（最终越限数{result.get('最终越限', {}).get('越限母线数', 0)}）"
            )

        elif tool_name == "_skill_load_sweep":
            details = result.get("负荷扫描结果", [])
            parts = []
            for d in details:
                parts.append(f"{d['倍率']}倍时过载{d['过载线路数']}条")
            summaries.append(f"负荷扫描Skill：{'，'.join(parts)}")

        elif tool_name == "_skill_load_sweep_step":
            details = result.get("负荷扫描结果", [])
            parts = []
            for d in details:
                if not d.get("潮流收敛", True):
                    parts.append(f"{d['倍率']}倍时潮流不收敛")
                else:
                    parts.append(f"{d['倍率']}倍时过载{d['过载线路数']}条")
            summaries.append(f"问答式负荷扫描：{'，'.join(parts)}")

        return "；".join(summaries) if summaries else "分析完成"
    
    def get_available_tools(self) -> Dict:
        """获取所有可用工具
        
        Returns:
            Dict: 工具列表
        """
        return {
            "question_id": self._generate_question_id(),
            "answer_output": {
                "status": "success",
                "available_tools": self.grid_tools.get_all_tools(),
            }
        }
    
    def get_conversation_history(self) -> List[Dict]:
        """获取对话历史
        
        Returns:
            List[Dict]: 对话历史列表
        """
        return self.conversation_history
    
    def clear_history(self) -> None:
        """清空对话历史"""
        self.conversation_history = []
        self.question_counter = 0
        self._load_sweep_state = {"active": False, "grid_type": None, "scenarios": []}


def main():
    """主函数 - 演示智能体使用"""
    # 创建智能体
    agent = PowerAgent()
    
    print("=" * 60)
    print("大电网静态安全分析智能体")
    print("基于pandapower库 v3.40")
    print("=" * 60)
    print()
    
    # 演示问题列表
    demo_questions = [
        "请进行交流潮流计算",
        "执行N-1静态安全校核",
        "分析线路过载情况",
        "检查电压越限",
        "计算网损",
        "进行电压稳定性分析",
        "执行三相短路计算",
    ]
    
    for i, question in enumerate(demo_questions, 1):
        print(f"\n{'─' * 50}")
        print(f"问题 {i}: {question}")
        print(f"{'─' * 50}")
        
        # 调用智能体回答
        response = agent.answer_question(question, grid_type="case9")
        
        # 输出结果
        print(f"\n问题ID: {response['question_id']}")
        print(f"分析类型: {response['answer_output']['analysis_type']}")
        print(f"状态: {response['answer_output']['status']}")
        print(f"摘要: {response['answer_output']['summary']}")
        print(f"\n详细数据:")
        
        # 格式化输出数据
        data = response['answer_output']['data']
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    print(f"  {key}: {len(value)} 条记录")
                    if len(value) > 0:
                        print(f"    示例: {json.dumps(value[0], ensure_ascii=False, indent=4)}")
                else:
                    print(f"  {key}: {value}")
        print()
    
    # 输出完整JSON示例
    print("\n" + "=" * 60)
    print("完整JSON输出示例（单个问题）:")
    print("=" * 60)
    example_response = agent.answer_question("请进行交流潮流计算", grid_type="case9")
    print(json.dumps(example_response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()