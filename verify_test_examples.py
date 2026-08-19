# -*- coding: utf-8 -*-
"""端到端验证《城市电网运行态势感知与协同调度决策》测评"测试任务示例"原始 9 条。

逐条把问题交给 PowerAgent（LLM 路由 + 工具执行），检查回答是否覆盖对应能力维度。
"""
import sys
import json

sys.path.insert(0, r"C:/Users/zry/Desktop/power-agent(1)/power-agent")

from power_agent import PowerAgent


def flatten(obj, out=None):
    """把嵌套结构拍平为可检索文本（同时包含 dict 的键与值）。"""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            flatten(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            flatten(v, out)
    else:
        out.append(str(obj))
    return out


# 9 条原始测试任务示例：(问题, 期望在回答文本中出现的信号关键词)
# 说明：示例7的"线路171"在 case39 中不存在（仅35条线路），属预期内的"指定元件不存在"，
# 智能体的正确表现是明确报告可用范围，而非编造结果。
EXAMPLES = [
    ("IEEE-39 节点系统中线路11连接哪两个母线？",
     ["连接", "Bus"], "识别分析对象(拓扑)"),
    ("母线电压正常运行范围是多少？",
     ["0.95", "1.05"], "计算方法(知识)"),
    ("N-1 静态安全校核需要检查哪些越限类型？",
     ["电压", "过载"], "计算方法(知识)"),
    ("某个潮流计算工具需要输入哪些参数？",
     ["算法", "迭代", "收敛", "参数"], "计算方法(知识)"),
    ("对 IEEE-39 节点系统运行交流潮流，并输出有功网损",
     ["总有功损耗", "网损"], "运行方式+输出要求"),
    ("筛选负载率最高的 5 条线路",
     ["Line", "负载率", "排序"], "筛选范围(Top-N)"),
    ("对线路171开展 N-1 校核",
     ["35", "编号", "解析", "N-1"], "指定元件对象(不存在时优雅处理)"),
    ("对关键线路逐一进行故障分析并排序",
     ["Top", "N-1", "风险", "排序", "逐一"], "多步复合任务"),
    ("根据仿真结果输出母线低电压、线路过载等风险及其证据",
     ["风险", "Bus"], "风险识别与证据输出"),
]


def main():
    agent = PowerAgent(use_llm=True)
    passed, failed = 0, 0
    print("=" * 70)
    print("测评示例端到端验证（agent 路由 + 工具执行）")
    print("=" * 70)

    for idx, (q, signals, dim) in enumerate(EXAMPLES, 1):
        r = agent.answer_question(q, grid_type="case39")
        ao = r.get("answer_output", {})
        summary = ao.get("summary", "")
        data_text = " ".join(flatten(ao.get("data", {})))
        tool = ao.get("analysis_type", "")
        status = ao.get("status", "")
        blob = (summary + " " + data_text + " " + ao.get("message", "")
                + " " + tool).lower()

        hit = [s for s in signals if s.lower() in blob]
        ok = len(hit) >= max(1, len(signals) - 1)  # 允许漏掉 1 个弱信号
        if ok:
            passed += 1
            tag = "OK"
        else:
            failed += 1
            tag = "FAIL"

        print(f"\n[{tag}] 示例{idx} ({dim})")
        print(f"  问题: {q}")
        print(f"  路由: {tool} | 状态: {status}")
        print(f"  摘要: {summary[:160]}")
        if not ok:
            print(f"  缺失信号: {[s for s in signals if s.lower() not in blob]}")
            print(f"  数据片段: {data_text[:200]}")

    print("\n" + "=" * 70)
    print(f"通过: {passed}  失败: {failed}  (共 {len(EXAMPLES)})")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
