# -*- coding: utf-8 -*-
import requests, json

PROMPT = (
    '2025-10-03 17:00 至 19:30期间，把"基态-750泉鱼断面B"控制到92%以下，'
    '其它断面最高不超过100%，给出平衡增减出力建议，'
    '并说明控制前后最大负载率，以及是否还有未解决的约束。'
)
SID = "test-007"
url = f"http://localhost:8000/api/sessions/{SID}/chat/stream"

print("=" * 70)
print("PROMPT:", PROMPT)
print("=" * 70)

current_tool = None
ai_output_parts = []

with requests.post(url, json={"question": PROMPT}, stream=True, timeout=600) as resp:
    resp.raise_for_status()
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        try:
            evt = json.loads(raw[6:])
        except Exception:
            continue
        ev = evt.get("event", "?")
        d = evt.get("data", {})

        if ev == "tool_start":
            current_tool = d.get("name", "?")
            print(f"\n▶ 调工具: 【{current_tool}】")
            print(f"  入参: {d.get('input', '')[:300]}")

        elif ev == "tool_end" and current_tool:
            out = d.get("output_preview", "")[:500]
            print(f"  ✓ 结果: {out}")
            current_tool = None

        elif ev == "token":
            ai_output_parts.append(d.get("text", ""))

        elif ev == "error":
            print(f"\n❌ 错误: {d}")

        elif ev == "done":
            print("\n" + "=" * 70)
            print("AI 完整回答:")
            print("=" * 70)
            print("".join(ai_output_parts))
            print("\n✅ 完成")