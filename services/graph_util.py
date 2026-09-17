import json
import math
from typing import Any, List, Dict, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage


def _safe_preview(obj: Any, max_len: int = 300) -> str:
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


def _sanitize_non_finite(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


def _parse_json_if_possible(text: Any) -> Any:
    if isinstance(text, str):
        try:
            return _sanitize_non_finite(json.loads(text))
        except Exception:
            return text
    return _sanitize_non_finite(text)


def _fill_tool_run(tool_runs: List[Dict[str, Any]], name: str, output: Any,
                   call_id: str = "") -> None:
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


def _messages_to_frontend_format(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    current_ai: Optional[Dict[str, Any]] = None

    for m in messages:
        if not isinstance(m, BaseMessage):
            continue

        if isinstance(m, HumanMessage):
            items.append({"role": "user", "content": m.content or ""})
            current_ai = None
            continue

        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            if current_ai is None:
                current_ai = {"role": "assistant", "content": "", "tool_runs": []}
                items.append(current_ai)
            for tc in m.tool_calls:
                current_ai.setdefault("tool_runs", []).append({
                    "name": tc.get("name", ""),
                    "input": tc.get("args") or {},
                    "output": None,
                    "status": "running",
                    "_call_id": tc.get("id", ""),
                })
            continue

        if isinstance(m, ToolMessage):
            call_id = getattr(m, "tool_call_id", "")
            output = _parse_json_if_possible(m.content)
            if current_ai is not None:
                _fill_tool_run(current_ai.get("tool_runs", []), m.name, output, call_id)
            continue

        if isinstance(m, AIMessage):
            content = m.content if isinstance(m.content, (str, list)) else str(m.content)
            if not content:
                continue
            if current_ai is not None:
                current_ai["content"] = content
                current_ai = None
            else:
                items.append({"role": "assistant", "content": content})
            continue
    return items