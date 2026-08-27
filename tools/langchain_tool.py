from langchain_core.tools import tool
from typing import Dict, List, Optional
from tools.grid_tools import GridTools


_sessions: Dict[str, GridTools] = {}


def get_gt_obj(session_id: str = "default") -> GridTools:
    if session_id not in _sessions:
        _sessions[session_id] = GridTools()
    return _sessions[session_id]


def _pop_session_id(kwargs: Dict) -> tuple[str, Dict]:
    sid = kwargs.pop("session_id", "default")
    return sid, kwargs


# ============================================================
# 原子工具薄壳：每个@tool对应GridTools.execute_tool的一个key
# ============================================================


@tool
def create_test_grid(grid_type: str = "case30", session_id: str = "default") -> Dict:
    """创建测试电网模型
    Args:
        grid_type: 电网类型，可选 case9/case14/case30/case39/case57/case118/case300/simple
        session_id: 会话ID，用于多会话隔离
    """
    try:
        gt = get_gt_obj(session_id)
        result = gt.create_test_grid(grid_type=grid_type)
        # 补丁：创建成功后把电网类型记到 GridTools 实例上，
        # 方便 session_service.get_session_grid_meta 存 MySQL，服务重启后恢复
        if result and result.get("success"):
            setattr(gt, "_patched_grid_type", grid_type)
        return result
    except Exception as e:
        return {"success": False, "message": f"创建电网失败: {str(e)}"}


@tool
def run_ac_power_flow(algorithm: str = "nr", max_iteration: int = 30,
                      tolerance: float = 1e-6, session_id: str = "default") -> Dict:
    """运行交流潮流计算，结果会缓存；仅当用户明确要求过载/电压等进一步分析时才调用其他工具
    Args:
        algorithm: 计算算法，nr(牛顿拉夫逊)/iwamoto_nr/fdbx/gs
        max_iteration: 最大迭代次数
        tolerance: 收敛精度
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.run_ac_power_flow(algorithm=algorithm,
                                     max_iteration=max_iteration,
                                     tolerance=tolerance)
    except Exception as e:
        return {"success": False, "message": f"潮流计算失败: {str(e)}"}


@tool
def run_n1_security_check(element_type: str = "line",
                           max_iterations: int = 30,
                           element_ids: List[int] = None,
                           session_id: str = "default") -> Dict:
    """执行N-1静态安全校核：逐个断开指定元件（默认全部线路）再算潮流，看是否过载或不收敛
    Args:
        element_type: 故障元件类型 line/trafo/bus
        max_iterations: 单次潮流最大迭代次数
        element_ids: 指定校核的元件索引列表（可为空，代表校核全部）
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.run_n1_security_check(element_type=element_type,
                                         max_iterations=max_iterations,
                                         element_ids=element_ids)
    except Exception as e:
        return {"success": False, "message": f"N-1校核失败: {str(e)}"}


@tool
def get_line_overload_summary(threshold: float = 80.0,
                               skip_runpp: bool = False,
                               session_id: str = "default") -> Dict:
    """线路/变压器过载分析：列出负载率超过阈值的元件
    Args:
        threshold: 过载阈值(%)，默认80，100表示满载
        skip_runpp: 是否跳过潮流计算（已有结果时传True）
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.get_line_overload_summary(threshold=threshold,
                                             skip_runpp=skip_runpp)
    except Exception as e:
        return {"success": False, "message": f"过载分析失败: {str(e)}"}


@tool
def get_voltage_violation_summary(vmin_pu: float = 0.95,
                                   vmax_pu: float = 1.05,
                                   skip_runpp: bool = False,
                                   session_id: str = "default") -> Dict:
    """母线电压越限分析：列出超出正常电压范围的母线
    Args:
        vmin_pu: 电压下限（标幺值），默认0.95
        vmax_pu: 电压上限（标幺值），默认1.05
        skip_runpp: 是否跳过潮流计算
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.get_voltage_violation_summary(vmin_pu=vmin_pu,
                                                 vmax_pu=vmax_pu,
                                                 skip_runpp=skip_runpp)
    except Exception as e:
        return {"success": False, "message": f"电压越限分析失败: {str(e)}"}


@tool
def set_load_scale(factor: float = 1.0, session_id: str = "default") -> Dict:
    """按倍率缩放整个电网的所有负荷（基于首次调用时的原始值，不会累积误差）
    factor=1.0可恢复原始负荷
    Args:
        factor: 负荷倍率，1.0=原始，2.0=两倍，0.8=八成
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.set_load_scale(factor=factor)
    except Exception as e:
        return {"success": False, "message": f"负荷缩放失败: {str(e)}"}


@tool
def generate_risk_report(vmin_pu: float = 0.95, vmax_pu: float = 1.05,
                          overload_threshold: float = 100.0,
                          top_n: int = 5, session_id: str = "default") -> Dict:
    """生成综合风险报告：合并电压越限、线路过载信息并给出风险排序和建议
    Args:
        vmin_pu: 电压下限
        vmax_pu: 电压上限
        overload_threshold: 过载阈值(%)
        top_n: 最多展示前N项风险
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.generate_risk_report(vmin_pu=vmin_pu, vmax_pu=vmax_pu,
                                        overload_threshold=overload_threshold,
                                        top_n=top_n)
    except Exception as e:
        return {"success": False, "message": f"生成风险报告失败: {str(e)}"}


@tool
def query_knowledge(topic: str = None, session_id: str = "default") -> Dict:
    """查询电网分析知识库（规程、定义、工具说明），不涉及任何计算
    Args:
        topic: 知识关键词，如 电压范围/N-1/潮流/短路/工具列表；为空返回全部
        session_id: 会话ID（仅用于统一接口，知识查询本身无状态）
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.query_knowledge(topic=topic)
    except Exception as e:
        return {"success": False, "message": f"知识查询失败: {str(e)}"}


@tool
def list_grid_elements(element_type: str = "all", session_id: str = "default") -> Dict:
    """列出当前电网中的元件清单（按分析对象维度）
    Args:
        element_type: bus/line/trafo/gen/load/ext_grid/all
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.list_grid_elements(element_type=element_type)
    except Exception as e:
        return {"success": False, "message": f"列出元件失败: {str(e)}"}


@tool
def analyze_with_outage(element_type: str, element_ids: List[int],
                         analysis: str = "power_flow",
                         vmin_pu: float = 0.95, vmax_pu: float = 1.05,
                         overload_threshold: float = 100.0,
                         session_id: str = "default") -> Dict:
    """在指定元件退出的假想工况下做分析（模拟检修或故障退出），退出仅影响本次分析
    Args:
        element_type: 退出元件类型 line/trafo/bus
        element_ids: 退出元件索引列表，例如 [3, 7]
        analysis: 分析类型 power_flow/voltage_violation/line_overload
        vmin_pu: 电压下限
        vmax_pu: 电压上限
        overload_threshold: 过载阈值(%)
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.analyze_with_outage(element_type=element_type,
                                       element_ids=element_ids,
                                       analysis=analysis,
                                       vmin_pu=vmin_pu,
                                       vmax_pu=vmax_pu,
                                       overload_threshold=overload_threshold)
    except Exception as e:
        return {"success": False, "message": f"退出工况分析失败: {str(e)}"}


@tool
def get_grid_topology(session_id: str = "default") -> Dict:
    """获取当前电网的拓扑结构信息（母线-线路连接关系、分区信息）
    Args:
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.get_grid_topology()
    except Exception as e:
        return {"success": False, "message": f"拓扑查询失败: {str(e)}"}


@tool
def calculate_loss_analysis(session_id: str = "default") -> Dict:
    """计算电网线损和变压器损耗（有功/无功损耗、损耗率）
    Args:
        session_id: 会话ID
    """
    try:
        gt = get_gt_obj(session_id)
        return gt.calculate_loss_analysis()
    except Exception as e:
        return {"success": False, "message": f"损耗分析失败: {str(e)}"}


@tool
def reset_grid_session(session_id: str = "default") -> Dict:
    """彻底重置当前会话的电网计算状态，清空所有缓存的电网模型、潮流结果、缩放倍率，
    恢复到未创建任何电网的初始干净状态。
    当用户明确要求"清空重来"、"恢复初始"、"不要之前的电网了"、"重新开始分析"，
    或表达要放弃之前的计算上下文时调用此工具。
    【注意】本工具仅清空计算状态，对话消息历史仍然保留，用户可以看到之前的聊天记录。
    Args:
        session_id: 会话ID
    """
    try:
        if session_id in _sessions:
            del _sessions[session_id]
        return {
            "success": True,
            "message": "当前会话的电网计算状态已彻底重置，"
                       "所有缓存的模型、结果、负荷倍率均已清空。"
                       "接下来如需要计算，请重新指定电网类型创建新模型。"
        }
    except Exception as e:
        return {"success": False, "message": f"重置会话失败: {str(e)}"}

# ============================================================
# 对外导出的工具清单（langchain_v1直接用）
# ============================================================
ATOMIC_TOOLS = [
    create_test_grid,
    run_ac_power_flow,
    run_n1_security_check,
    get_line_overload_summary,
    get_voltage_violation_summary,
    set_load_scale,
    generate_risk_report,
    query_knowledge,
    list_grid_elements,
    analyze_with_outage,
    get_grid_topology,
    calculate_loss_analysis,
    reset_grid_session,
]

ALL_TOOLS = ATOMIC_TOOLS