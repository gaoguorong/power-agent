# -*- coding: utf-8 -*-
"""
LLM客户端模块 - DeepSeek大模型集成

用于理解用户问题，智能选择分析工具和参数
工具清单通过 MCP tools/list 动态获取，不再硬编码
"""

import json
from typing import Dict, Any, List
from config.ts_config import LLM_CONFIG
from mcp.mcp_server import mcp_dispatch

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

# 系统提示词 - 只保留角色、电网选择、输出格式
# 工具清单通过 MCP tools/list 动态注入
SYSTEM_PROMPT_TEMPLATE = """你是一个电网静态安全分析智能体的工具调度模块。
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

## 可用分析工具列表（动态注入）：
{tools_description}

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
        """初始化LLM客户端（基于LangChain）
        
        Args:
            api_key: API密钥，为None时使用配置文件中的值
        """
        self.model = LLM_CONFIG["model"]
        self.api_key = LLM_CONFIG["api_key"]
        self.api_url = LLM_CONFIG["api_url_langchain"]
        self.temperature = LLM_CONFIG["temperature"]
        self.max_tokens = LLM_CONFIG["max_tokens"]
        self.timeout = LLM_CONFIG["timeout"]

        self.conversation_history = []


        self.llm = ChatOpenAI(
            model=self.model,
            base_url=self.api_url,
            api_key=self.api_key,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

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

        if not self._is_configured():
            return None
        
        try:
            tools_description = self._get_tools_description()
            
            system_prompt = SYSTEM_PROMPT_TEMPLATE.replace(
                "{tools_description}", tools_description
            )
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ]
            
            response = self._call_api(messages)
            result = self._parse_response(response)
            
            if "grid_type" not in result:
                result["grid_type"] = "case30"
            
            return result
            
        except Exception as e:
            print(f"[LLM] 调用失败: {e}")
            return None
    
    def _get_tools_description(self) -> str:

        try:

            json_temp = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "tools/list",
            }
            resp = mcp_dispatch(json_temp)
            
            if "error" in resp:
                print(f"[LLM] MCP tools/list 返回错误: {resp['error']}")
                return self._get_fallback_tools()
            
            tools = resp.get("result", {}).get("tools", [])
            
            lines = [f"共 {len(tools)} 个工具：\n"]
            for i, tool in enumerate(tools, 1):
                name = tool.get("name", "unknown")
                desc = tool.get("description", "")
                schema = tool.get("inputSchema", {})
                
                lines.append(f"{i}. **{name}** - {desc}")
                
                props = schema.get("properties", {})
                required = schema.get("required", [])
                if props:
                    lines.append("参数：")
                    for prop_name, prop_info in props.items():
                        pdesc = prop_info.get("description", "")
                        ptype = prop_info.get("type", "string")
                        req_mark = " (必填)" if prop_name in required else " (可选)"
                        lines.append(f"-{prop_name} ({ptype}){req_mark}: {pdesc}")
                else:
                    lines.append("参数：无")
                
                lines.append("")
            
            return "\n".join(lines)
            
        except Exception as e:
            print(f"[LLM] MCP tools/list 调用失败，使用备用清单: {e}")
            return self._get_fallback_tools()
    
    @staticmethod
    def _get_fallback_tools() -> str:
        """备用工具描述（当 MCP 不可用时使用）"""
        return """1. **run_ac_power_flow** - 交流潮流计算
   参数：无

2. **run_n1_security_check** - N-1静态安全校核
   参数：element_type (可选: line/trafo/bus，默认line)

3. **get_line_overload_summary** - 线路过载分析
   参数：threshold (默认80.0), skip_runpp (可选: bool)

4. **get_voltage_violation_summary** - 电压越限分析
   参数：vmin_pu (默认0.95), vmax_pu (默认1.05), skip_runpp (可选: bool)

5. **set_load_scale** - 按倍率调整负荷
   参数：factor (float, 必填: 负荷倍率)

6. **create_test_grid** - 创建测试电网
   参数：grid_type (case9/case14/case30/case39/case57/case118/case300/simple)

7. **get_grid_topology** - 获取电网拓扑
   参数：无

8. **list_grid_elements** - 列出元件清单
   参数：element_type (bus/line/trafo/gen/load/ext_grid/all)

9. **get_element_params** - 获取元件参数
   参数：element_type, element_id

10. **query_knowledge** - 查询电网知识
    参数：topic (可选)"""

    def _call_api(self, messages: List[BaseMessage]) -> str:
        """调用LLM（基于LangChain invoke）
        
        Args:
            messages: LangChain 消息列表（SystemMessage/HumanMessage等）
        
        Returns:
            str: LLM响应文本内容
        """
        result = self.llm.invoke(messages)
        if hasattr(result, "content"):
            return result.content
        return str(result)
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """解析LLM响应

        Args:
            response_text: LLM返回的文本

        Returns:
            Dict: 解析后的结果
        """
        # 尝试直接解析JSON
        try:
            cleaned = self._clean_json_response(response_text)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # 兜底：提取第一个 { 到最后一个 } 之间的内容
        try:
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = response_text[start:end + 1]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
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
        """与LLM进行对话（基于LangChain）
        
        Args:
            messages: 消息列表 [{role: "system"/"user"/"assistant", content: "..."}]
        
        Returns:
            str: LLM回复
        """
        if not self._is_configured():
            return "LLM未配置"

        try:
            lc_messages = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))

            response = self._call_api(lc_messages)
            return response
        except Exception as e:
            return f"调用失败: {str(e)}"


    def get_status(self) -> Dict[str, Any]:
        """获取LLM客户端状态
        
        Returns:
            Dict: 状态信息
        """
        return {
            "configured": self._is_configured(),
            "api_url": self.api_url,
            "model": self.model_name,
        }