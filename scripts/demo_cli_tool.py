# -*- coding: utf-8 -*-
"""
命令行测试脚本（给 CommandLineAdapter 验收用）

用法：
    python demo_cli_tool.py --a 2 --b 3          输出 JSON 求和结果
    python demo_cli_tool.py --fail               模拟失败（退出码1）
    python demo_cli_tool.py --sleep 5            模拟慢脚本（测超时）
"""
import argparse
import json
import sys
import time

parser = argparse.ArgumentParser(description="命令行适配器测试脚本")
parser.add_argument("--a", type=float, default=1.0)
parser.add_argument("--b", type=float, default=2.0)
parser.add_argument("--fail", action="store_true", help="模拟执行失败")
parser.add_argument("--sleep", type=float, default=0.0, help="先睡这么多秒")
args = parser.parse_args()

if args.sleep > 0:
    time.sleep(args.sleep)

if args.fail:
    print("模拟脚本执行失败", file=sys.stderr)
    sys.exit(1)

print(json.dumps({
    "success": True,
    "message": "demo cli ok",
    "sum": args.a + args.b,
}, ensure_ascii=False))
