# -*- coding: utf-8 -*-
"""
LLM 客户端：只负责「构造 ChatOpenAI」和「检查配置」两件事。

说明：历史上这里有过意图解析（parse_question + JSON 路由）等逻辑，
现已被 LangGraph 的 Function Calling 完全取代，故全部移除。
全项目统一通过 create_llm() 拿 LLM 实例，配置统一读 config.ts_config.LLM_CONFIG。
"""
from langchain_openai import ChatOpenAI

from config.ts_config import LLM_CONFIG


def is_llm_configured() -> bool:
    """API Key 是否已正确配置（占位符不算）"""
    api_key = LLM_CONFIG.get("api_key", "")
    return bool(api_key) and not api_key.startswith("sk-your-")


def create_llm() -> ChatOpenAI:
    """构造全项目共用的 ChatOpenAI 实例（GraphAgent 启动时调用一次）"""
    return ChatOpenAI(
        model=LLM_CONFIG["model"],
        base_url=LLM_CONFIG["api_url_langchain"],
        api_key=LLM_CONFIG["api_key"],
        temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["max_tokens"],
        timeout=LLM_CONFIG["timeout"],
    )
