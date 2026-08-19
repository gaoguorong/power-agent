# -*- coding: utf-8 -*-
"""
LLM客户端模块 - DeepSeek大模型集成

用于理解用户问题，智能选择分析工具和参数
"""

import json
import requests
from typing import Dict, Any, Optional, List
from config import LLM_CONFIG

# 系统提示词 - 告诉LLM可用的工具和如何选择
SYSTEM_PROMPT = """你是一个电网静态安全分析智能体的工具调度模块。
你的任务是理解用户的问题，并选择最合适的电网模型和分析工具。

## 电网模型选择（grid_type）：
- case9: IEEE 9节点系统（简单测试，适合入门演示）
- case14: IEEE 14节点系统（小型电网）
- case30: IEEE 30节点系统（常用测试系统，适合大多数分析）
- case39: IEEE 39节点系统（New英格兰系统，10台发电机，适合潮流和稳定分析）
- case57: IEEE 57节点系统（中型电网）
- case118: IEEE 118节点系统（大型电网）
- case300: IEEE 300节点系统（超大型电网，适合复杂分析）
- simple: 自定义简单电网

选择建议：
- 用户提到"简单"、"入门"、"小"时用case9
- 用户提到"标准"、"常用"或未指定时用case30
- 用户提到"39节点"、"新英格兰"或需要多发电机系统时用case39
- 用户提到"大型"、"复杂"、"N-1全校核"时用case118
- 用户提到"超大规模"、"300节点"时用case300

## 可用分析工具列表：

1. **run_ac_power_flow** - 交流潮流计算
   参数：无

2. **run_n1_security_check** - N-1静态安全校核
   参数：element_type (可选: line/trafo/bus，默认line)

3. **run_short_circuit_analysis** - 短路计算分析
   参数：fault_type (可选: 3phase/2phase/1phase，默认3phase)

4. **check_voltage_stability** - 电压稳定性分析
   参数：max_load_factor (默认2.0)

5. **get_line_overload_summary** - 线路过载分析
   参数：threshold (默认80.0)

6. **get_voltage_violation_summary** - 电压越限分析
   参数：vmin_pu (默认0.95), vmax_pu (默认1.05)

7. **calculate_loss_analysis** - 网损分析
   参数：无

8. **get_grid_topology** - 获取电网拓扑结构
   参数：无
   适用：用户问"列出所有母线/线路/发电机""某条线路连哪两个母线""电网有哪些元件"

9. **list_grid_elements** - 列出元件清单
   参数：element_type (可选: bus/line/trafo/gen/load/ext_grid/all，默认all)

10. **get_element_params** - 获取元件参数（电阻/电抗/容量/设定值等）
   参数：element_type (bus/line/trafo/gen/load/ext_grid),
        element_id (int 索引 或 名称字符串，如 "Bus 2"/"母线2"/"Line 1-2")

11. **query_knowledge** - 查询电网分析知识/元信息
   参数：topic (可选: 电压范围/N-1/工具/潮流/短路/频率，为空返回全部)
   适用：用户问"电压正常范围""N-1检查什么""有哪些工具""什么是潮流计算"

12. **rank_elements** - 按指标排序筛选(Top-N)
   参数：element_type (line/trafo/bus), metric (loading_percent/voltage/ploss_mw),
        top_n (默认5), order (desc/asc)
   适用：用户问"负载率最高的5条线路""电压最低的母线""损耗最大的变压器"

13. **analyze_element_security** - 对单一指定元件做N-1安全分析
   参数：element_type (line/trafo/bus), element_id (int 或 名称字符串)
   适用：用户问"对线路X做N-1分析""母线Y退出后是否安全"

14. **generate_risk_report** - 生成电网风险报告（含越限/过载证据与建议）
   参数：vmin_pu (默认0.95), vmax_pu (默认1.05),
        overload_threshold (默认100), top_n (默认5)
   适用：用户问"输出风险报告""有哪些电压越限/线路过载及其证据"

15. **analyze_with_outage** - 在指定元件退出的运行方式(检修方式)下做分析
   参数：element_type (line/trafo/bus), element_ids (列表),
        analysis (power_flow/voltage_violation/line_overload)
   适用：用户问"在退出某线路的运行方式下计算潮流""检修方式下有无越限"

## 选择建议补充：
- 用户问"结构/拓扑/连接/有哪些元件/列出了" → get_grid_topology 或 list_grid_elements
- 用户问"某元件的参数/R/X/容量/设定" → get_element_params
- 用户问"概念/准则/范围/有哪些工具/是什么" → query_knowledge
- 用户问"最高的N条/最低的几个/排序/Top" → rank_elements
- 用户问"对某个具体元件做N-1/某母线退出" → analyze_element_security
- 用户问"风险/越限/过载/报告/证据" → generate_risk_report
- 用户问"退出/检修/停运某元件后再分析" → analyze_with_outage
- element_id 既可以传整数索引，也可以传名称字符串（如 "Bus 2"、"母线2"、"Line 1-2"），系统会自动解析；
  若不确定索引，可先用 get_grid_topology 获取，但单轮对话中请直接依据用户给出的名称/编号填写。

## 输出格式要求：
你必须返回JSON格式：
{
    "grid_type": "推荐的电网类型",
    "tool_name": "工具名称",
    "tool_params": {},
    "reasoning": "选择的理由"
}

注意：
- 必须选择grid_type，不能省略
- 参数要准确，不要编造不存在的参数
- N-1校核涉及多条线路时推荐case30或case118
"""


class LLMClient:
    """DeepSeek LLM客户端"""
    
    def __init__(self, api_key: str = None):
        """初始化LLM客户端
        
        Args:
            api_key: API密钥，为None时使用配置文件中的值
        """
        self.api_key = api_key or LLM_CONFIG["api_key"]
        self.api_url = LLM_CONFIG["api_url"]
        self.model = LLM_CONFIG["model"]
        self.temperature = LLM_CONFIG["temperature"]
        self.max_tokens = LLM_CONFIG["max_tokens"]
        self.timeout = LLM_CONFIG["timeout"]
        self.conversation_history = []
    
    def _is_configured(self) -> bool:
        """检查API Key是否已正确配置
        
        Returns:
            bool: 是否已配置
        """
        if not self.api_key:
            return False
        if self.api_key.startswith("sk-your-"):
            return False
        return True
    
    def parse_question(self, question: str) -> Dict[str, Any]:
        """使用LLM解析用户问题，选择合适的电网和工具
        
        Args:
            question: 用户问题文本
        
        Returns:
            Dict: 包含grid_type, tool_name, tool_params, reasoning的结果
        """
        if not self._is_configured():
            # API Key未配置，返回None让调用者使用关键词匹配
            return None
        
        try:
            # 构建消息
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question}
            ]
            
            # 调用LLM
            response = self._call_api(messages)
            
            # 解析响应
            result = self._parse_response(response)
            
            # 确保返回结果包含grid_type
            if "grid_type" not in result:
                result["grid_type"] = "case30"
            
            return result
            
        except Exception as e:
            print(f"[LLM] 调用失败: {e}")
            return None
    
    def _call_api(self, messages: List[Dict]) -> str:
        """调用DeepSeek API
        
        Args:
            messages: 消息列表
        
        Returns:
            str: API响应内容
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        response = requests.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """解析LLM响应
        
        Args:
            response_text: LLM返回的文本
        
        Returns:
            Dict: 解析后的结果
        """
        # 尝试直接解析JSON
        try:
            # 清理可能的markdown格式
            cleaned = self._clean_json_response(response_text)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # 尝试用正则提取JSON
        try:
            import re
            # 查找JSON块
            match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            pass
        
        # 返回默认值
        return {
            "grid_type": "case30",
            "tool_name": "run_ac_power_flow",
            "tool_params": {},
            "reasoning": "默认使用case30进行潮流计算"
        }
    
    def _clean_json_response(self, text: str) -> str:
        """清理LLM响应中的Markdown格式
        
        Args:
            text: 原始文本
        
        Returns:
            str: 清理后的文本
        """
        # 移除```json和```标记
        text = text.replace("```json", "").replace("```", "")
        # 移除首尾空白
        text = text.strip()
        return text
    
    def chat(self, messages: List[Dict]) -> str:
        """与LLM进行对话
        
        Args:
            messages: 消息列表 [{role: "user", content: "..."}]
        
        Returns:
            str: LLM回复
        """
        if not self._is_configured():
            return "LLM未配置"
        
        try:
            response = self._call_api(messages)
            return response
        except Exception as e:
            return f"调用失败: {str(e)}"
    
    def set_api_key(self, api_key: str) -> None:
        """设置API Key
        
        Args:
            api_key: 新的API Key
        """
        self.api_key = api_key
    
    def get_status(self) -> Dict[str, Any]:
        """获取LLM客户端状态
        
        Returns:
            Dict: 状态信息
        """
        return {
            "configured": self._is_configured(),
            "api_url": self.api_url,
            "model": self.model,
        }