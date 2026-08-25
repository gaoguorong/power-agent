

_PF_DETAIL_FIELDS = {
    "母线电压": [], "线路潮流": [], "综合指标": {},
    "发电机输出": [], "负载功率": [],
}
SKIP_RUNPP_TOOLS = {"get_line_overload_summary", "get_voltage_violation_summary", "calculate_loss_analysis"}

# 问答式负荷扫描关键词集
LOAD_KW = ("负荷", "加载", "倍率", "倍", "水平", "调高", "调大",
           "加大", "增大", "增加", "提升", "放大", "提负荷", "加负荷")
BATCH_KW = ("扫描", "全扫", "全部倍率", "所有倍率", "批量")
FOLLOWUP_KW = ("对比", "比较", "结果", "情况", "有哪些", "出现", "存在",
               "过载", "概况", "怎么样", "如何", "多少")
RESCAN_KW = ("重新扫描", "重新分析", "再扫描", "再分析")