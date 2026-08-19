# -*- coding: utf-8 -*-
"""
电网静态安全分析智能体 - API服务

提供RESTful API接口，供外部系统调用
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

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from power_agent import PowerAgent
from config import AGENT_CONFIG

# 全局智能体实例
agent = PowerAgent()


class PowerAgentHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def do_GET(self):
        """处理GET请求"""
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            params = parse_qs(parsed_url.query)
            
            # 路由处理
            if path == "/" or path == "/index.html":
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
        """处理POST请求"""
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
        """健康检查接口"""
        response = {
            "status": "healthy",
            "service": AGENT_CONFIG["name"],
            "version": AGENT_CONFIG["version"],
            "agent_initialized": agent._initialized,
        }
        self._send_json(200, response)
    
    def _handle_get_tools(self):
        """获取可用工具列表"""
        result = agent.get_available_tools()
        self._send_json(200, result)
    
    def _handle_ask_question(self, params: dict):
        """处理提问请求(GET)"""
        question = params.get('question', [''])[0]
        grid_type = params.get('grid_type', [None])[0]  # 改为可选
        
        if not question:
            self._send_error(400, "缺少question参数")
            return
        
        try:
            # 如果指定了grid_type则使用指定的，否则自动选择
            result = agent.answer_question(question, grid_type=grid_type if grid_type else None)
            self._send_json(200, result)
        except Exception as e:
            self._send_error(500, str(e))
    
    def _handle_ask_question_post(self, params: dict):
        """处理提问请求(POST)"""
        question = params.get('question', '')
        grid_type = params.get('grid_type', None)  # 改为可选
        
        if not question:
            self._send_error(400, "缺少question字段")
            return
        
        try:
            # 如果指定了grid_type则使用指定的，否则自动选择
            result = agent.answer_question(question, grid_type=grid_type if grid_type else None)
            self._send_json(200, result)
        except Exception as e:
            self._send_error(500, str(e))
    
    def _handle_get_history(self):
        """获取对话历史"""
        history = agent.get_conversation_history()
        response = {
            "status": "success",
            "history_count": len(history),
            "history": history,
        }
        self._send_json(200, response)
    
    def _handle_get_config(self):
        """获取配置信息"""
        response = {
            "status": "success",
            "config": AGENT_CONFIG,
        }
        self._send_json(200, response)
    
    def _handle_create_grid(self, params: dict):
        """创建电网模型"""
        grid_type = params.get('grid_type', 'case9')
        
        from grid_tools import GridTools
        tools = GridTools()
        result = tools.create_test_grid(grid_type)
        
        if result['success']:
            self._send_json(200, {
                "question_id": agent._generate_question_id(),
                "answer_output": {
                    "status": "success",
                    "message": result['message'],
                    "grid_info": result['grid_info'],
                }
            })
        else:
            self._send_error(400, result['message'])
    
    def _handle_execute_tool(self, params: dict):
        """执行指定工具"""
        tool_name = params.get('tool_name', '')
        tool_params = params.get('tool_params', {})
        
        if not tool_name:
            self._send_error(400, "缺少tool_name参数")
            return
        
        from grid_tools import GridTools
        tools = GridTools()
        
        # 先创建电网（如果需要）
        grid_type = params.get('grid_type', 'case9')
        tools.create_test_grid(grid_type)
        
        # 执行工具
        result = tools.execute_tool(tool_name, **tool_params)
        
        self._send_json(200, {
            "question_id": agent._generate_question_id(),
            "answer_output": {
                "status": "success" if result.get('success') else "failed",
                "tool_name": tool_name,
                "result": result,
            }
        })
    
    def _handle_reset(self, params: dict):
        """重置智能体"""
        agent.clear_history()
        self._send_json(200, {
            "status": "success",
            "message": "智能体已重置",
        })
    
    def _handle_index_page(self):
        """返回首页HTML"""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html')
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            self._send_html(200, html_content)
        except FileNotFoundError:
            self._send_error(404, "页面文件不存在")
    
    def _handle_static_file(self, path: str):
        """处理静态文件请求（图片、CSS、JS等）"""
        # URL解码（处理中文文件名等）
        decoded_path = unquote(path)
        
        # 安全检查：防止路径遍历攻击
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
        file_path = os.path.join(web_dir, decoded_path.lstrip('/'))
        
        # 确保文件在web目录下
        if not os.path.abspath(file_path).startswith(os.path.abspath(web_dir)):
            self._send_error(403, "禁止访问")
            return
        
        if not os.path.isfile(file_path):
            self._send_error(404, "文件不存在")
            return
        
        # 获取文件MIME类型
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            self.send_response(200)
            self.send_header('Content-Type', f'{mime_type}; charset=utf-8' if 'text' in mime_type else mime_type)
            self.send_header('Content-Length', str(len(file_content)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(file_content)
        except Exception as e:
            self._send_error(500, f"读取文件失败: {str(e)}")
    
    def _send_html(self, status_code: int, html_content: str):
        """发送HTML响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def _send_json(self, status_code: int, data: dict):
        """发送JSON响应"""
        try:
            response_body = json.dumps(data, ensure_ascii=False, indent=2, default=self._json_serializer).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as e:
            print(f"[API] 发送响应失败: {str(e)}")
    
    @staticmethod
    def _json_serializer(obj):
        """自定义JSON序列化器，处理numpy/pandas类型"""
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Series):
            return obj.tolist()
        elif isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        else:
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    
    def _send_error(self, status_code: int, message: str):
        """发送错误响应"""
        self._send_json(status_code, {
            "status": "error",
            "message": str(message),
        })
    
    def log_message(self, format, *args):
        """日志消息"""
        print(f"[API] {args[0]}")


def start_server(host: str = "0.0.0.0", port: int = 8000):
    """启动API服务"""
    server = HTTPServer((host, port), PowerAgentHandler)
    print(f"{'=' * 60}")
    print(f"电网静态安全分析智能体 API服务")
    print(f"{'=' * 60}")
    print(f"服务地址: http://{host}:{port}")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"提问接口: http://{host}:{port}/api/question?question=xxx")
    print(f"工具列表: http://{host}:{port}/api/tools")
    print(f"历史记录: http://{host}:{port}/api/history")
    print(f"{'=' * 60}")
    print(f"按 Ctrl+C 停止服务")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n服务已停止")
        server.shutdown()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="电网静态安全分析智能体 API服务"
    )
    parser.add_argument(
        '--host', '-H',
        default='0.0.0.0',
        help='服务地址 (默认: 0.0.0.0)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=8000,
        help='端口号 (默认: 8000)'
    )
    
    args = parser.parse_args()
    
    start_server(args.host, args.port)


if __name__ == "__main__":
    main()