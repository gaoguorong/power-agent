# -*- coding: utf-8 -*-
"""
大电网静态安全分析智能体 - 使用示例

演示如何使用智能体进行各种电网分析任务
输出格式严格遵循要求：
{
    "question_id": "Q0001",  # 问题唯一编号
    "answer_output": {...}   # 输出答案
}
"""

import json
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from power_agent import PowerAgent
from tools.grid_tools import GridTools


def example_1_basic_usage():
    """示例1：基本用法 - 问答模式"""
    print("=" * 60)
    print("示例1：基本用法 - 问答模式")
    print("=" * 60)
    
    # 创建智能体
    agent = PowerAgent()
    
    # 提问
    response = agent.answer_question("请进行交流潮流计算", grid_type="case9")
    
    # 输出格式符合要求
    print(f"\n输出格式:")
    print(f"  question_id: {response['question_id']}")
    print(f"  answer_output: (包含分析结果)")
    
    # 打印详细结果
    print(f"\n分析类型: {response['answer_output']['analysis_type']}")
    print(f"摘要: {response['answer_output']['summary']}")
    print(f"状态: {response['answer_output']['status']}")
    
    return response


def example_2_sequential_questions():
    """示例2：连续提问 - 多轮对话"""
    print("\n" + "=" * 60)
    print("示例2：连续提问 - 多轮对话")
    print("=" * 60)
    
    agent = PowerAgent()
    
    questions = [
        "请进行交流潮流计算",
        "检查电压越限",
        "分析线路过载情况",
        "计算网损",
        "执行N-1静态安全校核",
        "进行电压稳定性分析",
    ]
    
    for q in questions:
        response = agent.answer_question(q, grid_type="case14")
        print(f"\n{response['question_id']}: {q}")
        print(f"  -> {response['answer_output']['summary']}")
    
    # 获取对话历史
    history = agent.get_conversation_history()
    print(f"\n对话历史记录数: {len(history)}")


def example_3_tool_direct_usage():
    """示例3：直接使用工具类"""
    print("\n" + "=" * 60)
    print("示例3：直接使用工具类")
    print("=" * 60)
    
    # 创建工具实例
    tools = GridTools()
    
    # 创建电网
    result = tools.create_test_grid("case30")
    print(f"\n电网创建: {result['message']}")
    print(f"电网信息: {json.dumps(result['grid_info'], ensure_ascii=False, indent=2)}")
    
    # 运行潮流计算
    pf_result = tools.run_ac_power_flow()
    print(f"\n潮流计算: {pf_result['message']}")
    
    if pf_result['success']:
        metrics = pf_result['综合指标']
        print(f"综合指标:")
        for k, v in metrics.items():
            print(f"  {k}: {v}")
    
    # 运行N-1校核
    n1_result = tools.run_n1_security_check(element_type="line")
    print(f"\nN-1校核: {n1_result['message']}")
    if n1_result['success']:
        stats = n1_result['统计信息']
        print(f"安全性评级: {stats['安全性评级']}")
        print(f"电压越限次数: {stats['电压越限次数']}")


def example_4_different_grid_types():
    """示例4：使用不同测试电网"""
    print("\n" + "=" * 60)
    print("示例4：使用不同测试电网")
    print("=" * 60)
    
    agent = PowerAgent()
    
    grid_types = ["case9", "case30", "case39", "case57", "case118"]
    
    for gt in grid_types:
        print(f"\n--- {gt} 电网 ---")
        response = agent.answer_question("请进行交流潮流计算", grid_type=gt)
        print(f"{response['answer_output']['summary']}")


def example_5_custom_parameters():
    """示例5：自定义参数调用"""
    print("\n" + "=" * 60)
    print("示例5：自定义参数调用")
    print("=" * 60)
    
    tools = GridTools()
    tools.create_test_grid("case9")
    
    # 自定义电压范围检查
    result = tools.get_voltage_violation_summary(vmin_pu=0.97, vmax_pu=1.03)
    print(f"\n自定义电压范围 [0.97, 1.03]:")
    print(f"  越限母线数: {result.get('越限母线数', 0)}")
    print(f"  总母线数: {result.get('总母线数', 0)}")
    
    # 自定义过载阈值
    result = tools.get_line_overload_summary(threshold=90.0)
    print(f"\n自定义过载阈值 90%:")
    print(f"  过载线路数: {result.get('过载线路数', 0)}")
    
    # 电压稳定性 - 高负载倍数
    result = tools.check_voltage_stability(max_load_factor=3.0)
    print(f"\n电压稳定性 (最大3倍负载):")
    print(f"  稳定裕度: {result.get('稳定裕度(%)', 0)}%")


def example_6_full_json_output():
    """示例6：完整JSON输出格式示例"""
    print("\n" + "=" * 60)
    print("示例6：完整JSON输出格式")
    print("=" * 60)
    
    agent = PowerAgent()
    
    # 执行各种分析
    analyses = [
        "请进行交流潮流计算",
        "执行N-1静态安全校核",
        "计算网损",
    ]
    
    for question in analyses:
        response = agent.answer_question(question, grid_type="case9")
        
        print(f"\n{'─' * 40}")
        print(f"问题: {question}")
        print(f"{'─' * 40}")
        print(f"完整JSON输出:")
        print(json.dumps(response, ensure_ascii=False, indent=2))


def example_7_available_tools():
    """示例7：查看所有可用工具"""
    print("\n" + "=" * 60)
    print("示例7：查看所有可用工具")
    print("=" * 60)
    
    agent = PowerAgent()
    tools_info = agent.get_available_tools()
    
    print(f"\n可用工具列表:")
    for tool in tools_info['answer_output']['available_tools']:
        print(f"\n  工具名: {tool['name']}")
        print(f"  描述: {tool['description']}")
        print(f"  参数: {tool['parameters']}")


def example_8_history_context():
    """示例8：历史会话上下文功能 - 多轮对话复用潮流结果
    
    演示场景：
    1. 用户输入"基于30节点电网模型进行潮流计算" -> 执行潮流计算
    2. 用户输入"是否出现线路过载" -> 基于之前潮流结果查询
    3. 用户输入"是否出现电压越限" -> 基于之前潮流结果查询
    """
    print("\n" + "=" * 60)
    print("示例8：历史会话上下文功能")
    print("=" * 60)
    print("\n演示多轮对话：潮流计算 -> 线路过载查询 -> 电压越限查询")
    print("（后两个查询将自动复用第一次潮流计算的结果）\n")
    
    agent = PowerAgent()
    
    # 第一轮：进行潮流计算
    print("【第1轮】用户: 基于30节点电网模型进行潮流计算")
    response1 = agent.answer_question("基于30节点电网模型进行潮流计算", grid_type="case30")
    print(f"  问题ID: {response1['question_id']}")
    print(f"  分析类型: {response1['answer_output']['analysis_type']}")
    print(f"  摘要: {response1['answer_output']['summary']}")
    print(f"  状态: {response1['answer_output']['status']}")
    
    # 第二轮：查询线路过载（应复用潮流结果）
    print("\n【第2轮】用户: 是否出现线路过载？")
    response2 = agent.answer_question("是否出现线路过载？")
    print(f"  问题ID: {response2['question_id']}")
    print(f"  分析类型: {response2['answer_output']['analysis_type']}")
    print(f"  摘要: {response2['answer_output']['summary']}")
    print(f"  状态: {response2['answer_output']['status']}")
    
    # 第三轮：查询电压越限（应复用潮流结果）
    print("\n【第3轮】用户: 是否出现电压越限？")
    response3 = agent.answer_question("是否出现电压越限？")
    print(f"  问题ID: {response3['question_id']}")
    print(f"  分析类型: {response3['answer_output']['analysis_type']}")
    print(f"  摘要: {response3['answer_output']['summary']}")
    print(f"  状态: {response3['answer_output']['status']}")
    
    # 第四轮：查询网损（同样复用潮流结果）
    print("\n【第4轮】用户: 计算当前网损情况")
    response4 = agent.answer_question("计算当前网损情况")
    print(f"  问题ID: {response4['question_id']}")
    print(f"  分析类型: {response4['answer_output']['analysis_type']}")
    print(f"  摘要: {response4['answer_output']['summary']}")
    print(f"  状态: {response4['answer_output']['status']}")
    
    # 展示对话历史
    history = agent.get_conversation_history()
    print(f"\n对话历史记录数: {len(history)}")
    for record in history:
        print(f"  - {record['question_id']}: {record['question'][:30]}... -> {record['tool_used']}")
    
    # 返回详细的最后一个响应
    return response3


def main():
    """运行所有示例"""
    print("#" * 60)
    print("# 大电网静态安全分析智能体 - 使用示例")
    print("# 基于pandapower库 v3.40")
    print("#" * 60)
    
    # 运行示例
    try:
        example_1_basic_usage()
    except Exception as e:
        print(f"示例1执行失败: {e}")
    
    try:
        example_2_sequential_questions()
    except Exception as e:
        print(f"示例2执行失败: {e}")
    
    try:
        example_3_tool_direct_usage()
    except Exception as e:
        print(f"示例3执行失败: {e}")
    
    try:
        example_4_different_grid_types()
    except Exception as e:
        print(f"示例4执行失败: {e}")
    
    try:
        example_5_custom_parameters()
    except Exception as e:
        print(f"示例5执行失败: {e}")
    
    try:
        example_6_full_json_output()
    except Exception as e:
        print(f"示例6执行失败: {e}")
    
    try:
        example_7_available_tools()
    except Exception as e:
        print(f"示例7执行失败: {e}")
    
    try:
        example_8_history_context()
    except Exception as e:
        import traceback
        print(f"示例8执行失败: {e}")
        traceback.print_exc()
    
    print("\n" + "#" * 60)
    print("# 所有示例执行完成")
    print("#" * 60)


if __name__ == "__main__":
    main()