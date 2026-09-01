# -*- coding: utf-8 -*-
"""
CommandLineAdapter：调用独立命令行脚本

安全硬要求（一条都不能少）：
- 参数必须用列表形式传给 subprocess，禁止拼 shell 字符串
- 支持超时，超时强制终止
- 捕获退出码、标准输出、标准错误
- 脚本路径在注册时就定死，用户不能传任意可执行文件路径
"""
import json
import subprocess
import sys
from pathlib import Path

from executors.base import ToolAdapter, ToolExecutionRequest
from schemas.tool_result import ToolError, ToolResult, normalize_tool_result


class CommandLineAdapter(ToolAdapter):

    def __init__(self, script_path: str, interpreter: str = None):
        self.script_path = Path(script_path)
        # 默认用当前 Python 解释器跑 .py 脚本
        self.interpreter = interpreter or sys.executable

    def validate(self, request: ToolExecutionRequest) -> None:
        if not self.script_path.exists():
            raise ValueError(f"脚本不存在: {self.script_path}")

    def _build_cmd(self, parameters: dict) -> list:
        """dict → 参数列表。如 {"a": 2} → ["--a", "2"]；布尔 True → 只传开关 "--flag" """
        cmd = [self.interpreter, str(self.script_path)]
        for k, v in parameters.items():
            if isinstance(v, bool):
                if v:
                    cmd.append(f"--{k}")
            else:
                cmd.extend([f"--{k}", str(v)])
        return cmd

    def execute(self, request: ToolExecutionRequest) -> dict:
        self.validate(request)
        cmd = self._build_cmd(request.parameters)

        try:
            # 列表形式 + 不经过 shell，参数里有什么都不可能被当命令执行
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                code="SYS_ERROR",
                message=f"工具 {request.tool_id} 超时（>{request.timeout_seconds}秒），已终止",
                error=ToolError(type="timeout", retryable=True),
            ).model_dump()

        # 非零退出码：脚本自己报的错，把 stderr 带回来方便排查
        if proc.returncode != 0:
            return ToolResult(
                success=False,
                code="SYS_ERROR",
                message=f"工具 {request.tool_id} 脚本异常退出（退出码 {proc.returncode}）",
                error=ToolError(type="system", retryable=False,
                                details={"returncode": proc.returncode,
                                         "stderr": (proc.stderr or "")[:500]}),
            ).model_dump()

        # 正常退出：stdout 是 JSON 就解析，否则原文放进 data
        stdout = (proc.stdout or "").strip()
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict):
            return normalize_tool_result(raw, request.tool_id)
        return ToolResult(
            success=True,
            code="OK",
            message=f"{request.tool_id} 执行成功",
            data={"stdout": stdout},
        ).model_dump()
