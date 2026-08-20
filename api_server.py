# -*- coding: utf-8 -*-
"""
电网静态安全分析智能体 - API服务

提供 RESTful API 接口，供外部系统调用。
所有工具调用统一委托给 MCP 引擎 (mcp_dispatch)，确保状态共享。

输出格式：{question_id, answer_output}
"""

import json
import sys
import os
import mimetypes
import argparse
import numpy as np
import pandas as pd
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from power_agent import PowerAgent
from mcp_server import mcp_dispatch, _get_state, _json_default
from config import AGENT_CONFIG

state = _get_state()

agent = PowerAgent()
agent.grid_tools = state.tools
agent._initialized = True
agent.current_grid_type = "case9"


class PowerAgentHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""

    def do_GET(self):
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            params = parse_qs(parsed_url.query)

            if path in ("/", "/index.html"):
                self._handle_index_page()
            elif path.startswith("/assets/"):
                self._handle_static_file(path)
            elif path == "/health":
                self._handle_health_check()
            elif path == "/api/tools":
                self._handle_get_tools()
            elif path == "/api/question":
                self._handle_ask_question(params)
            elif path == "/api/history":
                self._handle_get_history()
            elif path == "/api/config":
                self._handle_get_config()
            else:
                self._send_error(404, "接口不存在")
        except Exception as e:
            self._send_error(500, f"服务器内部错误: {str(e)}")

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)

            try:
                params = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError:
                self._send_error(400, "无效的JSON数据")
                return

            parsed_url = urlparse(self.path)
            path = parsed_url.path

            if path == "/api/question":
                self._handle_ask_question_post(params)
            elif path == "/api/grid/create":
                self._handle_create_grid(params)
            elif path == "/api/tool/execute":
                self._handle_execute_tool(params)
            elif path == "/api/reset":
                self._handle_reset(params)
            else:
                self._send_error(404, "接口不存在")
        except Exception as e:
            try:
                self._send_error(500, f"服务器内部错误: {str(e)}")
            except Exception:
                pass

    def _handle_health_check(self):
        response = {
            "status": "healthy",
            "service": AGENT_CONFIG["name"],
            "version": AGENT_CONFIG["version"],
            "agent_initialized": agent._initialized,
            "grid_initialized": state.tools.net is not None,
        }
        self._send_json(200, response)

    def _handle_get_tools(self):
        resp = mcp_dispatch({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "tools/list",
        })
        tools = resp.get("result", {}).get("tools", [])
        self._send_json(200, {
            "question_id": agent._generate_question_id(),
            "answer_output": {
                "status": "success",
                "count": len(tools),
                "tools": tools,
            }
        })

    def _handle_ask_question(self, params: dict):
        question = params.get('question', [''])[0]
        grid_type = params.get('grid_type', [None])[0]

        if not question:
            self._send_error(400, "缺少question参数")
            return

        try:
            result = agent.answer_question(
                question,
                grid_type=grid_type if grid_type else None
            )
            self._send_json(200, result)
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_ask_question_post(self, params: dict):
        question = params.get('question', '')
        grid_type = params.get('grid_type', None)

        if not question:
            self._send_error(400, "缺少question字段")
            return

        try:
            result = agent.answer_question(
                question,
                grid_type=grid_type if grid_type else None
            )
            self._send_json(200, result)
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_get_history(self):
        history = agent.get_conversation_history()
        self._send_json(200, {
            "status": "success",
            "history_count": len(history),
            "history": history,
        })

    def _handle_get_config(self):
        self._send_json(200, {
            "status": "success",
            "config": AGENT_CONFIG,
        })

    def _handle_create_grid(self, params: dict):
        grid_type = params.get('grid_type', 'case9')

        result = state.execute("create_test_grid", grid_type=grid_type)

        if not result.get("success", True):
            self._send_error(400, result.get("message", "创建电网失败"))
        else:
            self._send_json(200, {
                "question_id": agent._generate_question_id(),
                "answer_output": {
                    "status": "success",
                    "message": result.get("message", "电网创建成功"),
                    "grid_info": result.get("grid_info", {}),
                }
            })

    def _handle_execute_tool(self, params: dict):
        tool_name = params.get('tool_name', '')
        tool_params = params.get('tool_params', {})

        if not tool_name:
            self._send_error(400, "缺少tool_name参数")
            return

        result = state.execute(tool_name, **tool_params)

        self._send_json(200, {
            "question_id": agent._generate_question_id(),
            "answer_output": {
                "status": "success" if result.get("success", True) else "failed",
                "tool_name": tool_name,
                "result": result,
            }
        })

    def _handle_reset(self, params: dict):
        state.reset()
        agent.grid_tools = state.tools
        agent._initialized = True
        agent.current_grid_type = "case9"
        agent.clear_history()
        self._send_json(200, {
            "status": "success",
            "message": "智能体已重置",
        })

    def _handle_index_page(self):
        html_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html'
        )
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            self._send_html(200, html_content)
        except FileNotFoundError:
            self._send_error(404, "页面文件不存在")

    def _handle_static_file(self, path: str):
        decoded_path = unquote(path)
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
        file_path = os.path.join(web_dir, decoded_path.lstrip('/'))

        if not os.path.abspath(file_path).startswith(os.path.abspath(web_dir)):
            self._send_error(403, "禁止访问")
            return

        if not os.path.isfile(file_path):
            self._send_error(404, "文件不存在")
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'

        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()

            self.send_response(200)
            self.send_header(
                'Content-Type',
                f'{mime_type}; charset=utf-8' if 'text' in mime_type else mime_type
            )
            self.send_header('Content-Length', str(len(file_content)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(file_content)
        except Exception as e:
            self._send_error(500, f"读取文件失败: {str(e)}")

    def _send_html(self, status_code: int, html_content: str):
        self.send_response(status_code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))

    def _send_json(self, status_code: int, data: dict):
        try:
            response_body = json.dumps(
                data, ensure_ascii=False, indent=2, default=_json_default
            ).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as e:
            print(f"[API] 发送响应失败: {str(e)}")

    def _send_error(self, status_code: int, message: str):
        self._send_json(status_code, {
            "status": "error",
            "message": str(message),
        })

    def log_message(self, format, *args):
        print(f"[API] {args[0]}")


def start_server(host: str = "0.0.0.0", port: int = 8000):
    server = HTTPServer((host, port), PowerAgentHandler)
    print("=" * 60)
    print("电网静态安全分析智能体 API服务")
    print("=" * 60)
    print(f"服务地址: http://{host}:{port}")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"提问接口: http://{host}:{port}/api/question?question=xxx")
    print(f"工具列表: http://{host}:{port}/api/tools")
    print(f"历史记录: http://{host}:{port}/api/history")
    print("=" * 60)
    print("按 Ctrl+C 停止服务")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="电网静态安全分析智能体 API服务"
    )
    parser.add_argument(
        "--host", "-H",
        default="0.0.0.0",
        help="服务地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="端口号 (默认: 8000)"
    )

    args = parser.parse_args()
    start_server(args.host, args.port)


if __name__ == "__main__":
    main()