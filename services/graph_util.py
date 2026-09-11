# ==============================================================
# 模块内小工具函数
# ==============================================================
import json
import math
from typing import List, Dict, Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage


def _msg_role(m: BaseMessage) -> str:
    """LangChain Message 类型 → 前端认识的 role 字符串"""
    if isinstance(m, HumanMessage):
        return "user"
    if isinstance(m, AIMessage):
        return "assistant"
    if isinstance(m, ToolMessage):
        return "tool"
    return type(m).__name__.lower()


def _fill_tool_run(tool_runs: List[Dict[str, Any]], name: str, output: Any,
                   call_id: str = "") -> None:
    """把执行结果回填到 tool_runs 里对应的 running 记录。

    优先按 tool_call_id 精确配对：同一工具在一轮里被并行调用多次时（如连续
    load_grid_from_file 两个文件），只按名字配对会把结果填错块（输入 .json
    却显示加载了 .p）。call_id 缺失时才退回按名字配对最近一条 running。
    """
    if call_id:
        for run in reversed(tool_runs):
            if run.get("_call_id") == call_id and run["status"] == "running":
                run["output"] = _safe_preview(output)
                run["status"] = "ok"
                return
    for run in reversed(tool_runs):
        if run["name"] == name and run["status"] == "running":
            run["output"] = _safe_preview(output)
            run["status"] = "ok"
            return


def _sanitize_non_finite(obj: Any) -> Any:
    """递归把 NaN / Infinity 等非有限浮点替换成 None。

    工具结果里偶尔会算出 NaN（如孤立线路的负载率均值），Python json.dumps
    默认会把它写成字面量 NaN 存起来；刷新恢复历史时 FastAPI 的 JSONResponse
    （allow_nan=False）再序列化就会抛 ValueError。统一在边界清洗成 None。
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


def _parse_json_if_possible(text: Any) -> Any:
    """工具输出是 JSON 字符串就解析成 dict（前端展示更好看），否则原样返回。
    解析后统一清洗 NaN/Infinity，兼容数据库里已存了 NaN 字面量的历史记录。"""
    if isinstance(text, str):
        try:
            return _sanitize_non_finite(json.loads(text))
        except Exception:
            return text
    return _sanitize_non_finite(text)


def _safe_preview(obj: Any, max_len: int = 300) -> str:
    """任意对象 → 短字符串预览（前端气泡展示用，避免大 JSON 塞爆页面）"""
    try:
        if obj is None:
            return ""
        if isinstance(obj, str):
            text = obj
        elif isinstance(obj, (dict, list)):
            text = json.dumps(obj, ensure_ascii=False, default=str)
        else:
            text = str(obj)
        return text if len(text) <= max_len else text[:max_len] + "..."
    except Exception:
        return "[无法预览]"


def _messages_to_frontend_format(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """LangChain 消息历史 → 前端 ChatMessage[] 结构。

    原始历史里一次问答 = user + ai(tool_calls) + tool*N + ai(正文)，
    前端实时聊天渲染时是把工具调用都挂在一条 assistant 消息的 tool_runs 上，
    所以这里同样做聚合，恢复出来的界面才和实时聊天一致。
    """
    items: List[Dict[str, Any]] = []
    current_ai: Optional[Dict[str, Any]] = None  # 当前正在聚合的 assistant 消息

    for m in messages:
        if not isinstance(m, BaseMessage):
            continue

        if isinstance(m, HumanMessage):
            items.append({"role": "user", "content": m.content or ""})
            current_ai = None
            continue

        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            # 带工具调用的 AI 消息：开（或复用）一条 assistant，把调用挂到 tool_runs
            if current_ai is None:
                current_ai = {"role": "assistant", "content": "", "tool_runs": []}
                items.append(current_ai)
            for tc in m.tool_calls:
                current_ai.setdefault("tool_runs", []).append({
                    "name": tc.get("name", ""),
                    "input": tc.get("args") or {},
                    "output": None,
                    "status": "running",
                    # 内部字段：给下一条 ToolMessage 配对用，前端用不到但无害
                    "_call_id": tc.get("id", ""),
                })
            continue

        if isinstance(m, ToolMessage):
            # 工具结果：按 tool_call_id 回填到最近一条 running 的同名调用
            call_id = getattr(m, "tool_call_id", "")
            output = _parse_json_if_possible(m.content)
            if current_ai is not None:
                for run in reversed(current_ai.get("tool_runs", [])):
                    if run.get("_call_id") == call_id and run["status"] == "running":
                        run["output"] = output
                        run["status"] = "ok"
                        break
            continue

        if isinstance(m, AIMessage):
            # 纯正文回答：填进正在聚合的 assistant；没有就新开一条
            content = m.content if isinstance(m.content, (str, list)) else str(m.content)
            if not content:
                continue
            if current_ai is not None:
                current_ai["content"] = content
                current_ai = None
            else:
                items.append({"role": "assistant", "content": content})
            continue
        # SystemMessage 等不参与前端渲染，跳过
    return items


def _message_to_persist(m: BaseMessage) -> Dict[str, Any]:
    """LangChain Message → 可 JSON 序列化的持久化结构（存 MySQL）"""
    item: Dict[str, Any] = {
        "t": _msg_role(m),
        "content": m.content if isinstance(m.content, (str, list)) else str(m.content),
    }
    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        # 保留 id：恢复后要和 ToolMessage.tool_call_id 配对，LLM 才认得这是完整的工具调用链
        item["tool_calls"] = [
            {
                "name": tc.get("name"),
                "args": tc.get("args") or {},
                "id": tc.get("id"),
                "type": tc.get("type", "tool_call"),
            }
            for tc in m.tool_calls
        ]
    if isinstance(m, ToolMessage):
        item["name"] = getattr(m, "name", "")
        item["tool_call_id"] = getattr(m, "tool_call_id", "")
    return item


def _persist_to_message(item: Dict[str, Any]) -> Optional[BaseMessage]:
    """持久化结构 → LangChain Message（从 MySQL 恢复时用）"""
    role = item.get("t")
    content = item.get("content", "")
    if role == "user":
        return HumanMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content, tool_calls=item.get("tool_calls") or [])
    if role == "tool":
        return ToolMessage(
            content=content,
            name=item.get("name", ""),
            tool_call_id=item.get("tool_call_id", ""),
        )
    if role == "system":
        return SystemMessage(content=content)
    return None