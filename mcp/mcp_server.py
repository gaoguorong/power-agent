import json
import sys
import os
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.grid_tools import GridTools
from config.model_config import AGENT_CONFIG, SUPPORTED_GRID_TYPES
import numpy as np
import pandas as pd
from skills.skill_def import VOLTAGE_CORRECTION_SKILL, LOAD_SWEEP_SKILL
from skills.skill_runner import run_load_sweep

MCP_PROTOCOL_VERSION = "2024-11-05"


# ============================================================
# 模块级工具函数
# ============================================================

def _serialize(obj):
    """把 numpy/pandas 类型转为 JSON 可序列化的 Python 原生类型"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return obj


def _json_default(obj):
    """json.dumps 的 default 回调"""
    result = _serialize(obj)
    if result is not obj:
        return result
    return str(obj)


def _err(req_id, code, message):
    """构造 JSON-RPC 错误响应"""
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ============================================================
# MCP 工具构建
# ============================================================

def _build_json_schema_from_params(params: dict) -> dict:
    """将工具参数描述转换为 JSON Schema object

    输入: {"param_name": "type - description"}
    输出: {"type": "object", "properties": {...}}
    """
    properties = {}
    for pname, pdesc in params.items():
        parts = pdesc.split(" - ", 1)
        ptype = parts[0].strip().lower()
        pdesc_text = parts[1].strip() if len(parts) > 1 else ""

        schema_type = "string"
        if ptype in ("int", "integer"):
            schema_type = "integer"
        elif ptype in ("float", "number"):
            schema_type = "number"
        elif ptype in ("bool", "boolean"):
            schema_type = "boolean"
        elif ptype in ("list", "array"):
            schema_type = "array"
        elif ptype in ("dict", "object"):
            schema_type = "object"

        properties[pname] = {"type": schema_type, "description": pdesc_text}

    return {"type": "object", "properties": properties}


def _get_skill_tools() -> list:
    """将 Skill 定义暴露为 MCP 工具，让 LLM 能直接选择高层编排"""

    skill_defs = [
        (VOLTAGE_CORRECTION_SKILL, "_skill_voltage_correction"),
        (LOAD_SWEEP_SKILL, "_skill_load_sweep"),
    ]

    tools = []
    for skill, tool_name in skill_defs:
        tools.append({
            "name": tool_name,
            "description": f"[Skill] {skill['description']}",
            "inputSchema": {"type": "object", "properties": {}},
        })

    tools.append({
        "name": "_composite_n1_rank",
        "description": "[Skill] 关键线路N-1复合分析：识别系统关键线路并排序，基于N-1安全校核结果给出风险分级",
        "inputSchema": {"type": "object", "properties": {}},
    })

    return tools


def _build_mcp_tools(grid_tools: GridTools) -> list:
    """构建完整 MCP 工具列表 = 原子工具 + Skill 高层工具"""
    atomic = [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": _build_json_schema_from_params(t.get("parameters", {})),
        }
        for t in grid_tools.get_all_tools()
    ]
    return atomic + _get_skill_tools()


# ============================================================
# MCP 状态管理（懒加载单例）
# ============================================================

class MCPState:
    """MCP 服务器状态管理

    维护一个共享的 GridTools 实例。
    支持 create_test_grid / set_load_scale 等工具修改电网状态。
    """

    def __init__(self):
        self.tools = GridTools()
        self.tools.create_test_grid("case9")

    def reset(self):
        self.tools = GridTools()
        self.tools.create_test_grid("case9")

    def create_grid(self, grid_type: str) -> dict:
        return self.tools.create_test_grid(grid_type)

    def execute(self, tool_name: str, **kwargs) -> dict:
        if tool_name == "create_test_grid":
            return self.create_grid(kwargs.get("grid_type", "case9"))
        if tool_name == "_skill_load_sweep":
            return _run_skill_load_sweep(self.tools)
        return self.tools.execute_tool(tool_name, **kwargs)


_mcp_state = None


def _get_state() -> MCPState:
    """懒加载获取 MCPState 单例"""
    global _mcp_state
    if _mcp_state is None:
        _mcp_state = MCPState()
    return _mcp_state


# ============================================================
# 核心: MCP 分发引擎（纯函数，可本地调用）
# ============================================================

def _run_skill_load_sweep(tools: GridTools) -> dict:
    """执行负荷扫描 Skill（2x/4x 倍率扫描线路过载），把生成器事件汇总成工具结果。

    Skill 快速通道执行器是同步 generator，这里逐条消费：
    tool 事件合并进结果明细，final 事件作为最终答复；扫描结束后负荷倍率已恢复 1.0。
    """
    steps = []
    final_text = ""
    detail = {}
    aborted = False
    try:
        for ev in run_load_sweep(tools, LOAD_SWEEP_SKILL):
            if ev.get("kind") == "tool":
                steps.append({
                    "工具": ev.get("name"),
                    "输入": ev.get("input"),
                    "结果": ev.get("output"),
                })
            elif ev.get("kind") == "final":
                final_text = ev.get("text", "")
                detail = ev.get("detail", {})
                aborted = bool(ev.get("aborted"))
        if aborted:
            return {"success": False, "message": final_text or "前置条件不满足"}
        return {
            "success": True,
            "message": final_text or "负荷扫描完成",
            "执行步骤": steps,
            **detail,
        }
    except Exception as e:
        return {"success": False, "message": f"负荷扫描执行异常: {str(e)}"}


def mcp_dispatch(request_body: dict) -> dict:

    if not isinstance(request_body, dict):
        return _err(None, -32600, "Invalid Request")

    req_id = request_body.get("id")
    method = request_body.get("method", "")
    params = request_body.get("params", {})

    state = _get_state()

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": AGENT_CONFIG["name"],
                    "version": AGENT_CONFIG["version"],
                    "description": AGENT_CONFIG.get("description", ""),
                },
                "instructions": (
                    "电力系统静态安全分析工具服务器。"
                    "支持潮流计算、N-1安全校核、短路分析、电压稳定性分析、"
                    "线路过载检测、电压越限分析、网损计算、电网拓扑查询等。"
                    "使用 create_test_grid 选择电网模型后，可调用其他分析工具。"
                ),
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _build_mcp_tools(state.tools)},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": "缺少工具名称 (name)"}],
                    "isError": True,
                },
            }

        try:
            result = state.execute(tool_name, **arguments)
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"工具执行异常: {str(e)}"}],
                    "isError": True,
                },
            }

        if result is None:
            result = {"success": False, "message": "工具返回空结果"}

        is_error = not result.get("success", True)
        output_text = json.dumps(_serialize(result), ensure_ascii=False, indent=2)

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": output_text}],
                "isError": is_error,
            },
        }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    elif method == "notifications/initialized":
        return None

    else:
        return _err(req_id, -32601, f"Method not found: {method}")


# ============================================================
# HTTP 处理器（委托给 mcp_dispatch）
# ============================================================

class MCPHandler(BaseHTTPRequestHandler):
    """MCP HTTP 请求处理器

    所有 JSON-RPC 请求统一委托给 mcp_dispatch，
    避免 HTTP 层与业务逻辑耦合。
    """

    server_version = "Power MCP Server v2.0"

    def log_message(self, format, *args):
        print(f"[MCP] {args[0]}")

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        state = _get_state()

        if path in ("/mcp", "/"):
            self._send_json(200, {
                "status": "ok",
                "service": self.server_version,
                "mcp_endpoint": "POST /mcp",
                "methods": ["initialize", "tools/list", "tools/call", "ping"],
            })
        elif path == "/health":
            self._send_json(200, {
                "status": "healthy",
                "service": self.server_version,
                "grid_initialized": state.tools.net is not None,
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path not in ("/mcp", "/"):
            self._send_json(404, _err(None, -32601, f"Endpoint not found: {path}"))
            return

        body = self._read_body()
        resp = mcp_dispatch(body)

        if resp is None:
            self.send_response(202)
            self.end_headers()
            return

        self._send_json(200, resp)


# ============================================================
# 服务器启动
# ============================================================

def start_server(host: str = "0.0.0.0", port: int = 9000):
    server = HTTPServer((host, port), MCPHandler)

    state = _get_state()
    tool_count = len(_build_mcp_tools(state.tools))

    print("=" * 60)
    print("  Power Grid MCP Server")
    print("=" * 60)
    print(f"  服务地址: http://{host}:{port}")
    print(f"  MCP 端点: POST /mcp")
    print(f"  健康检查: http://{host}:{port}/health")
    print(f"  协议版本: {MCP_PROTOCOL_VERSION}")
    print(f"  初始电网: case9")
    print(f"  可用工具数: {tool_count}")
    print()
    print("  MCP 方法:")
    print("    initialize    初始化握手")
    print("    tools/list    查询工具列表")
    print("    tools/call    调用工具")
    print("    ping          健康检查")
    print()
    print("  按 Ctrl+C 停止服务")
    print("=" * 60)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMCP Server 已停止")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="电力系统静态安全分析 MCP Server"
    )
    parser.add_argument(
        "--host", "-H",
        default="0.0.0.0",
        help="服务地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9000,
        help="端口号 (默认: 9000)"
    )

    args = parser.parse_args()
    start_server(args.host, args.port)


if __name__ == "__main__":
    main()