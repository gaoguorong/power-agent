# -*- coding: utf-8 -*-
"""
Agent 层：智能体定义
- llm_client  ：LLM 实例工厂（create_llm / is_llm_configured）
- graph_agent ：LangGraph 状态机（agent → inject_session → tools → agent …）
                只管图结构和节点逻辑，对外由 services/graph_service.py 驱动
"""
from .llm_client import create_llm, is_llm_configured
from .graph_agent import GraphAgent

__all__ = ["create_llm", "is_llm_configured", "GraphAgent"]
