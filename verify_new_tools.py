"""本地验证脚本：在 case39 模型下实测新增工具与智能体路由。
不依赖 DeepSeek（走关键词兜底路由）。
"""
import json
import traceback
from grid_tools import GridTools
from power_agent import PowerAgent

PASS, FAIL = [], []

def check(name, fn):
    try:
        r = fn()
        ok = bool(r and r.get("success"))
        (PASS if ok else FAIL).append(name)
        print(f"[{'OK' if ok else 'FAIL'}] {name}")
        if not ok:
            print("   msg:", r.get("message") if isinstance(r, dict) else r)
        return r
    except Exception as e:
        FAIL.append(name)
        print(f"[ERROR] {name}: {e}")
        traceback.print_exc()
        return None

gt = GridTools()
print("=== 初始化 case39 ===")
init = gt.create_test_grid("case39")
print("init:", init.get("success"), init.get("message"))

# 1. 拓扑
r1 = check("get_grid_topology", lambda: gt.get_grid_topology())
if r1:
    print("   母线数:", len(r1.get("母线列表", [])), "线路数:", len(r1.get("线路连接", [])),
          "变压器数:", len(r1.get("变压器连接", [])), "发电机数:", len(r1.get("发电机列表", [])))

# 2. 列出元件
check("list_grid_elements(all)", lambda: gt.list_grid_elements("all"))
check("list_grid_elements(line)", lambda: gt.list_grid_elements("line"))

# 3. 元件参数（用名称/中文引用解析）
check("get_element_params(line 名称引用)", lambda: gt.get_element_params("line", "Line 1-2"))
check("get_element_params(bus 中文引用)", lambda: gt.get_element_params("bus", "Bus 2"))
check("get_element_params(gen)", lambda: gt.get_element_params("gen", 0))

# 4. 知识查询
check("query_knowledge(电压范围)", lambda: gt.query_knowledge("电压"))
check("query_knowledge(全部)", lambda: gt.query_knowledge())

# 5. 排序 Top-N
r5 = check("rank_elements(line loading desc)", lambda: gt.rank_elements("line", "loading_percent", 5, "desc"))
if r5:
    print("   负载率最高:", [(x.get("名称"), x.get("指标值")) for x in r5.get("排名结果", [])][:3])

# 6. 单元件 N-1
r6 = check("analyze_element_security(line 1-2)", lambda: gt.analyze_element_security("line", "Line 1-2"))
if r6:
    print("   安全:", r6.get("安全"), "电压越限:", r6.get("电压越限数"), "过载:", r6.get("过载数"))

# 7. 运行方式（退出某线路）
r7 = check("analyze_with_outage(line [1-2])", lambda: gt.analyze_with_outage("line", ["Line 1-2"], "power_flow"))
if r7:
    print("   潮流收敛:", r7.get("潮流收敛"), "退出元件:", r7.get("退出元件"))

# 8. 风险报告
r8 = check("generate_risk_report", lambda: gt.generate_risk_report())
if r8:
    print("   风险等级:", r8.get("风险等级"), "风险总数:", r8.get("风险总数"))

# 9. N-1 指定线路（增强能力）
check("run_n1_security_check(line 指定)", lambda: gt.run_n1_security_check("line", element_ids=[0, 1, 2]))

# 10. 智能体路由（关键词兜底）
print("\n=== 智能体问答（关键词路由）===")
agent = PowerAgent()
questions = [
    "列出电网的所有母线和线路",            # topology
    "查询线路 Line 1-2 的参数",            # element params
    "电网电压正常范围是怎样的",            # knowledge
    "找出负载率最高的5条线路",             # rank
    "对线路 Line 1-2 做 N-1 安全分析",     # element security
    "若线路 Line 1-2 退出运行，分析潮流",  # outage
    "生成电网风险报告",                    # risk report
    "对关键线路逐一做N-1并排序",           # composite
]
for q in questions:
    def run(q=q):
        ans = agent.answer_question(q, grid_type="case39")
        ao = ans.get("answer_output", {})
        return {"success": ao.get("status") == "success",
                "tool": ao.get("analysis_type"),
                "msg": ao.get("summary") or ao.get("message")}
    rr = check(f"agent: {q}", run)
    if rr and rr.get("tool"):
        print("   路由到:", rr.get("tool"), "| 摘要:", str(rr.get("msg"))[:60])

print("\n=== 汇总 ===")
print(f"通过: {len(PASS)}  失败: {len(FAIL)}")
if FAIL:
    print("失败项:", FAIL)
