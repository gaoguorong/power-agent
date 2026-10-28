# -*- coding: utf-8 -*-
import json
import sys
import requests

BASE = "http://127.0.0.1:8000"

question = (
    '前瞻调度 2025-10-03 17:00至19:30期间，把"基态-750泉鱼断面B"控制到92%以下，'
    "其它断面最高不超过100%，给出平衡增减出力建议，"
    "并说明控制前后最大负载率，以及是否还有未解决的约束。"
)

print("=" * 60)
print("创建 session...")
r = requests.post(f"{BASE}/api/sessions", json={"name": "断面控制测试"})
r.raise_for_status()
data = r.json()["data"]
session_id = data["id"]
print(f"session_id = {session_id}")

print("=" * 60)
print(f"发送问题: {question}")
print("=" * 60)

url = f"{BASE}/api/sessions/{session_id}/chat/stream"
with requests.post(url, json={"question": question}, stream=True, timeout=180) as resp:
    resp.raise_for_status()
    tool_calls = []
    final_text = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                evt = json.loads(payload)
            except json.JSONDecodeError:
                continue
            ev_type = evt.get("event")
            ev_data = evt.get("data", {})
            if ev_type == "tool_start":
                name = ev_data.get("name", "")
                args = ev_data.get("input", {})
                tool_calls.append(name)
                print(f"[TOOL START] {name}  args={json.dumps(args, ensure_ascii=False)[:300]}")
            elif ev_type == "tool_end":
                name = ev_data.get("name", "")
                out = ev_data.get("output_preview", "")
                print(f"[TOOL END]   {name}  out={str(out)[:200]}")
            elif ev_type == "token":
                final_text += ev_data.get("text", "")
            elif ev_type == "done":
                print("[DONE]")
            elif ev_type == "error":
                print(f"[ERROR] {ev_data.get('message')}")

print("=" * 60)
print("工具调用链:")
for i, t in enumerate(tool_calls, 1):
    print(f"  {i}. {t}")
print("=" * 60)
print("AI 最终回答:")
sys.stdout.reconfigure(encoding="utf-8")
print(final_text)