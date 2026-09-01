# -*- coding: utf-8 -*-
"""
通用响应包装 + 序列化工具
- ApiResponse / ok / fail ：所有普通接口的统一返回格式
- json_dumps_safe         ：安全 JSON 序列化（SSE 事件体用）
"""
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """所有普通接口的统一返回格式"""
    code: int = Field(default=0, description="0=成功，其他=错误码")
    message: str = Field(default="success", description="错误说明或成功提示")
    data: Optional[Any] = Field(default=None, description="业务数据")


# 下面这个是给工具函数用的：快速构造成功/失败响应
def ok(data: Any = None, message: str = "success") -> Dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 400, data: Any = None) -> Dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def json_dumps_safe(obj: Any) -> str:
    """安全的 json.dumps（遇到奇怪的类型不会炸）"""
    return json.dumps(obj, ensure_ascii=False, default=str)
