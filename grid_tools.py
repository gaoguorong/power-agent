# -*- coding: utf-8 -*-
"""
大电网静态安全分析工具模块
基于pandapower库封装电网分析功能，供智能体调用
"""

import pandapower as pp
import pandapower.networks as pn
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import json
import copy


class GridTools:
    """电网静态安全分析工具类
    
    封装pandapower库的各种计算功能：
    - 交流潮流计算
    - N-1静态安全校核
    - 短路计算
    - 电压稳定性分析
    - 线路/变压器负载率分析
    - 母线电压越限检查
    """
    
    def __init__(self):
        """初始化电网工具"""
        self.net = None
        self.results_cache = {}
    
    def create_test_grid(self, grid_type: str = "case9") -> Dict:
        """创建测试电网模型
        
        Args:
            grid_type: 电网类型，可选 case9, case14, case30, case39, case57, case118, case300
                    或 'simple' 创建简单电网
        
        Returns:
            Dict: 创建结果信息
        """
        try:
            if grid_type == "case9":
                self.net = pn.case9()
            elif grid_type == "case14":
                self.net = pn.case14()
            elif grid_type == "case30":
                self.net = pn.case30()
            elif grid_type == "case39":
                self.net = self._create_case39()
            elif grid_type == "case57":
                self.net = pn.case57()
            elif grid_type == "case118":
                self.net = pn.case118()
            elif grid_type == "case300":
                self.net = pn.case300()
            elif grid_type == "simple":
                self.net = self._create_simple_grid()
            else:
                return {"success": False, "message": f"不支持的电网类型: {grid_type}"}

            self._load_original_p_mw = None
            self._load_original_q_mvar = None

            grid_info = self._get_grid_info()
            return {"success": True, "message": "电网模型创建成功", "grid_info": grid_info}
        except Exception as e:
            return {"success": False, "message": f"创建电网失败: {str(e)}"}
    
    def _create_simple_grid(self) -> pp.pandapowerNet:
        """创建简单的测试电网
        
        Returns:
            pandapowerNet: 简单电网模型
        """
        net = pp.create_empty_network()
        
        # 创建母线
        bus1 = pp.create_bus(net, vn_kv=110., name="高压母线")
        bus2 = pp.create_bus(net, vn_kv=110., name="中压母线")
        bus3 = pp.create_bus(net, vn_kv=110., name="低压母线")
        
        # 创建外部电网（平衡节点）
        pp.create_ext_grid(net, bus=bus1, vm_pu=1.0, va_degree=0.0, name="外部电网")
        
        # 创建发电机
        pp.create_gen(net, bus=bus2, p_mw=100., vm_pu=1.02, name="发电机1", controllable=True)
        
        # 创建负载
        pp.create_load(net, bus=bus2, p_mw=60., q_mvar=20., name="负载1")
        pp.create_load(net, bus=bus3, p_mw=40., q_mvar=15., name="负载2")
        
        # 创建线路
        pp.create_line(net, from_bus=bus1, to_bus=bus2, length_km=10.,
                       std_type="NAYY 4x50 SE", name="线路1")
        pp.create_line(net, from_bus=bus2, to_bus=bus3, length_km=8.,
                       std_type="NAYY 4x50 SE", name="线路2")
        
        # 创建变压器
        pp.create_transformer(net, hv_bus=bus1, lv_bus=bus3, 
                             std_type="63 MVA 110/20 kV", name="变压器1")
        
        return net
    
    def _create_case39(self) -> pp.pandapowerNet:

        try:
            net = pp.networks.case39()
            for i in net.bus.index:
                net.bus.at[i, "name"] = f"Bus {int(i) + 1}"
            for j in net.line.index:
                fb = int(net.line.at[j, "from_bus"]) + 1
                tb = int(net.line.at[j, "to_bus"]) + 1
                net.line.at[j, "name"] = f"Line {fb}-{tb}"
            for k in net.trafo.index:
                net.trafo.at[k, "name"] = f"Trafo {int(k) + 1}"
            for m in net.gen.index:
                net.gen.at[m, "name"] = f"Generator {int(m) + 1}"
            net.sn_mva = 100
            return net
        except Exception:
            # 回退：若标准模型不可用，则按下方手工建模
            # （注意：手工版本拓扑不完整，部分场景可能不收敛）
            pass
        # 兼容不同 pandapower 版本：旧版 create_empty_network 不接受 freq_hz 参数，
        # 统一创建后显式设置频率与基准容量。
        net = pp.create_empty_network()
        try:
            net["f_hz"] = 60
        except Exception:
            pass
        net.sn_mva = 100
        
        # ==================== 创建母线 ====================
        # 39个母线，主要电压等级230kV
        bus_data = [
            ("Bus 1", 230.), ("Bus 2", 230.), ("Bus 3", 230.), ("Bus 4", 230.),
            ("Bus 5", 230.), ("Bus 6", 230.), ("Bus 7", 230.), ("Bus 8", 230.),
            ("Bus 9", 230.), ("Bus 10", 230.), ("Bus 11", 230.), ("Bus 12", 230.),
            ("Bus 13", 230.), ("Bus 14", 230.), ("Bus 15", 230.), ("Bus 16", 230.),
            ("Bus 17", 230.), ("Bus 18", 230.), ("Bus 19", 230.), ("Bus 20", 230.),
            ("Bus 21", 230.), ("Bus 22", 230.), ("Bus 23", 230.), ("Bus 24", 230.),
            ("Bus 25", 230.), ("Bus 26", 230.), ("Bus 27", 230.), ("Bus 28", 230.),
            ("Bus 29", 230.), ("Bus 30", 230.), ("Bus 31", 230.), ("Bus 32", 230.),
            ("Bus 33", 230.), ("Bus 34", 230.), ("Bus 35", 230.), ("Bus 36", 230.),
            ("Bus 37", 230.), ("Bus 38", 230.), ("Bus 39", 230.),
        ]
        bus_ids = []
        for name, vn_kv in bus_data:
            bus_id = pp.create_bus(net, vn_kv=vn_kv, name=name)
            bus_ids.append(bus_id)
        
        # ==================== 创建发电机 ====================
        # 母线30为平衡节点（参考母线）
        pp.create_ext_grid(net, bus=bus_ids[30], vm_pu=1.0, va_degree=0.0, name="Generator 30")
        
        # 其他9台发电机
        gen_data = [
            (bus_ids[31], 104.0, 1.0, "Generator 31"),   # Bus 31
            (bus_ids[32], 72.0, 1.0, "Generator 32"),    # Bus 32
            (bus_ids[33], 380.0, 1.0, "Generator 33"),   # Bus 33
            (bus_ids[34], 482.0, 1.0, "Generator 34"),   # Bus 34
            (bus_ids[35], 20.0, 1.0, "Generator 35"),    # Bus 35
            (bus_ids[36], 155.0, 1.0, "Generator 36"),   # Bus 36
            (bus_ids[37], 0.0, 1.0, "Generator 37"),     # Bus 37 (同步调相机)
            (bus_ids[38], 0.0, 1.0, "Generator 38"),     # Bus 38 (同步调相机)
            (bus_ids[39 - 1], 1000.0, 1.0, "Generator 39"),  # Bus 39
        ]
        for bus, p_mw, vm_pu, name in gen_data:
            pp.create_gen(net, bus=bus, p_mw=p_mw, vm_pu=vm_pu, name=name, controllable=True)
        
        # ==================== 创建负荷 ====================
        load_data = [
            (bus_ids[0], 5.0, 1.8, "Load 1"),      # Bus 1
            (bus_ids[1], 150.0, 53.0, "Load 2"),   # Bus 2
            (bus_ids[2], 420.0, 10.0, "Load 3"),   # Bus 3
            (bus_ids[3], 580.0, 200.0, "Load 4"),  # Bus 4
            (bus_ids[4], 300.0, 98.0, "Load 5"),   # Bus 5
            (bus_ids[5], 0.0, 0.0, "Load 6"),      # Bus 6
            (bus_ids[6], 0.0, 0.0, "Load 7"),      # Bus 7
            (bus_ids[7], 0.0, 0.0, "Load 8"),      # Bus 8
            (bus_ids[8], 0.0, 0.0, "Load 9"),      # Bus 9
            (bus_ids[9], 0.0, 0.0, "Load 10"),     # Bus 10
            (bus_ids[10], 0.0, 0.0, "Load 11"),    # Bus 11
            (bus_ids[11], 0.0, 0.0, "Load 12"),    # Bus 12
            (bus_ids[12], 0.0, 0.0, "Load 13"),    # Bus 13
            (bus_ids[13], 0.0, 0.0, "Load 14"),    # Bus 14
            (bus_ids[14], 0.0, 0.0, "Load 15"),    # Bus 15
            (bus_ids[15], 0.0, 0.0, "Load 16"),    # Bus 16
            (bus_ids[16], 0.0, 0.0, "Load 17"),    # Bus 17
            (bus_ids[17], 0.0, 0.0, "Load 18"),    # Bus 18
            (bus_ids[18], 0.0, 0.0, "Load 19"),    # Bus 19
            (bus_ids[19], 0.0, 0.0, "Load 20"),    # Bus 20
            (bus_ids[20], 0.0, 0.0, "Load 21"),    # Bus 21
            (bus_ids[21], 0.0, 0.0, "Load 22"),    # Bus 22
            (bus_ids[22], 0.0, 0.0, "Load 23"),    # Bus 23
            (bus_ids[23], 0.0, 0.0, "Load 24"),    # Bus 24
            (bus_ids[24], 0.0, 0.0, "Load 25"),    # Bus 25
            (bus_ids[25], 0.0, 0.0, "Load 26"),    # Bus 26
            (bus_ids[26], 0.0, 0.0, "Load 27"),    # Bus 27
            (bus_ids[27], 0.0, 0.0, "Load 28"),    # Bus 28
            (bus_ids[28], 0.0, 0.0, "Load 29"),    # Bus 29
        ]
        for bus, p_mw, q_mvar, name in load_data:
            if p_mw > 0 or q_mvar > 0:
                pp.create_load(net, bus=bus, p_mw=p_mw, q_mvar=q_mvar, name=name)
        
        # 母线39的负荷
        pp.create_load(net, bus=bus_ids[38], p_mw=1100.0, q_mvar=250.0, name="Load 39")
        
        # ==================== 创建线路 ====================
        # 使用标准线路类型
        line_std = "NAYY 4x50 SE"
        line_data = [
            # (from_bus, to_bus, length_km)
            (bus_ids[0], bus_ids[1], 10.0),    # 1-2
            (bus_ids[0], bus_ids[2], 10.0),    # 1-3
            (bus_ids[0], bus_ids[3], 10.0),    # 1-4
            (bus_ids[0], bus_ids[4], 10.0),    # 1-5
            (bus_ids[0], bus_ids[5], 10.0),    # 1-6
            (bus_ids[1], bus_ids[2], 10.0),    # 2-3
            (bus_ids[1], bus_ids[4], 10.0),    # 2-5
            (bus_ids[2], bus_ids[3], 10.0),    # 3-4
            (bus_ids[3], bus_ids[4], 10.0),    # 4-5
            (bus_ids[3], bus_ids[5], 10.0),    # 4-6
            (bus_ids[5], bus_ids[6], 10.0),    # 6-7
            (bus_ids[5], bus_ids[30], 10.0),   # 6-31
            (bus_ids[6], bus_ids[7], 10.0),    # 7-8
            (bus_ids[7], bus_ids[8], 10.0),    # 8-9
            (bus_ids[7], bus_ids[31], 10.0),   # 8-32
            (bus_ids[8], bus_ids[9], 10.0),    # 9-10
            (bus_ids[8], bus_ids[32], 10.0),   # 9-33
            (bus_ids[9], bus_ids[10], 10.0),   # 10-11
            (bus_ids[9], bus_ids[33], 10.0),   # 10-34
            (bus_ids[10], bus_ids[11], 10.0),  # 11-12
            (bus_ids[10], bus_ids[34], 10.0),  # 11-35
            (bus_ids[11], bus_ids[12], 10.0),  # 12-13
            (bus_ids[11], bus_ids[35], 10.0),  # 12-36
            (bus_ids[12], bus_ids[13], 10.0),  # 13-14
            (bus_ids[12], bus_ids[36], 10.0),  # 13-37
            (bus_ids[13], bus_ids[14], 10.0),  # 14-15
            (bus_ids[13], bus_ids[37], 10.0),  # 14-38
            (bus_ids[14], bus_ids[15], 10.0),  # 15-16
            (bus_ids[14], bus_ids[38], 10.0),  # 15-39
            (bus_ids[15], bus_ids[16], 10.0),  # 16-17
            (bus_ids[15], bus_ids[17], 10.0),  # 16-18
            (bus_ids[16], bus_ids[17], 10.0),  # 17-18
            (bus_ids[17], bus_ids[18], 10.0),  # 18-19
            (bus_ids[18], bus_ids[19], 10.0),  # 19-20
        ]
        for from_bus, to_bus, length_km in line_data:
            pp.create_line(net, from_bus=from_bus, to_bus=to_bus,
                          length_km=length_km, std_type=line_std,
                          name=f"Line {from_bus+1}-{to_bus+1}")
        
        # ==================== 创建变压器 ====================
        # 发电机通过变压器连接到母线
        trafo_data = [
            (bus_ids[30], bus_ids[30], "Generator 30"),  # Ext_grid at bus 30
            (bus_ids[31], bus_ids[31], "Generator 31"),
            (bus_ids[32], bus_ids[32], "Generator 32"),
            (bus_ids[33], bus_ids[33], "Generator 33"),
            (bus_ids[34], bus_ids[34], "Generator 34"),
            (bus_ids[35], bus_ids[35], "Generator 35"),
            (bus_ids[36], bus_ids[36], "Generator 36"),
            (bus_ids[37], bus_ids[37], "Generator 37"),
            (bus_ids[38], bus_ids[38], "Generator 38"),
            (bus_ids[39 - 1], bus_ids[39 - 1], "Generator 39"),
        ]
        for hv_bus, lv_bus, name in trafo_data:
            # 跨 pandapower 版本兼容：旧版 std_types 库含 "40 MVA 230/110 kV"，
            # 3.4 已移除该型号，改用参数化创建（本模型发电机经单位变比变压器接入母线）。
            pp.create_transformer_from_parameters(
                net, hv_bus=hv_bus, lv_bus=lv_bus,
                sn_mva=40, vn_hv_kv=230, vn_lv_kv=230,
                vkr_percent=0.5, vk_percent=12.0,
                pfe_kw=50, i0_percent=0.2,
                tap_side="hv", tap_neutral=0.0, tap_min=0.0, tap_max=0.0,
                tap_step_percent=0.0, name=name)
        
        return net

    def _get_grid_info(self) -> Dict:
        """获取电网基本信息
        
        Returns:
            Dict: 电网信息
        """
        if self.net is None:
            return {}
        
        info = {
            "总线数": len(self.net.bus),
            "线路数": len(self.net.line),
            "变压器数": len(self.net.trafo),
            "发电机数": len(self.net.gen),
            "负载数": len(self.net.load),
            "母线列表": self.net.bus["name"].tolist(),
        }
        return info
    
    def run_ac_power_flow(self, **kwargs) -> Dict:
        """运行交流潮流计算
        
        Args:
            **kwargs: 潮流计算参数
                - algorithm: 计算算法 (nr, iwamoto_nr, etc.)
                - max_iteration: 最大迭代次数
                - tolerance: 收敛精度
        
        Returns:
            Dict: 潮流计算结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            # 运行潮流计算
            pp.runpp(self.net, **kwargs)
            
            if self.net.converged:
                # 收集结果
                result = {
                    "success": True,
                    "message": "潮流计算收敛",
                    "线路潮流": self._get_line_results(),
                    "变压器潮流": self._get_trafo_results(),
                    "母线电压": self._get_bus_results(),
                    "发电机输出": self._get_gen_results(),
                    "负载功率": self._get_load_results(),
                }
                
                # 计算综合指标
                result["综合指标"] = self._calculate_overall_metrics()
                
                self.results_cache["ac_power_flow"] = result
                return result
            else:
                return {"success": False, "message": "潮流计算不收敛"}
        except Exception as e:
            return {"success": False, "message": f"潮流计算失败: {str(e)}"}
    
    def _safe_get_col(self, df, idx, col, default=0.0):
        """安全获取列值，兼容不同版本pandapower
        
        Args:
            df: DataFrame
            idx: 索引
            col: 列名
            default: 默认值
        
        Returns:
            列值
        """
        if col in df.columns:
            return df.loc[idx, col]
        # 尝试查找可能的替代列名
        col_map = {
            "ploss_mw": ["p_loss_mw", "ploss", "p_from_mw", "p_to_mw"],
            "qloss_mvar": ["q_loss_mvar", "qloss", "q_from_mvar", "q_to_mvar"],
            "loading_percent": ["loading", "load_percent"],
        }
        if col in col_map:
            for alt_col in col_map[col]:
                if alt_col in df.columns:
                    return df.loc[idx, alt_col]
        return default
    
    def _get_line_results(self) -> List[Dict]:
        """获取线路潮流结果
        
        Returns:
            List[Dict]: 线路结果列表
        """
        results = []
        if len(self.net.res_line) > 0:
            for idx in self.net.res_line.index:
                line_info = {
                    "线路ID": int(idx),
                    "名称": self.net.line.loc[idx, "name"],
                    "有功损失": round(self._safe_get_col(self.net.res_line, idx, "ploss_mw"), 4),
                    "无功损失": round(self._safe_get_col(self.net.res_line, idx, "qloss_mvar"), 4),
                    "线路负载率": round(
                        max(self._safe_get_col(self.net.res_line, idx, "loading_percent"), 0), 2
                    ),
                }
                results.append(line_info)
        return results
    
    def _get_trafo_results(self) -> List[Dict]:
        """获取变压器潮流结果
        
        Returns:
            List[Dict]: 变压器结果列表
        """
        results = []
        if len(self.net.res_trafo) > 0:
            for idx in self.net.res_trafo.index:
                trafo_info = {
                    "变压器ID": int(idx),
                    "名称": self.net.trafo.loc[idx, "name"],
                    "有功损失": round(self._safe_get_col(self.net.res_trafo, idx, "ploss_mw"), 4),
                    "无功损失": round(self._safe_get_col(self.net.res_trafo, idx, "qloss_mvar"), 4),
                    "变压器负载率": round(
                        max(self._safe_get_col(self.net.res_trafo, idx, "loading_percent"), 0), 2
                    ),
                }
                results.append(trafo_info)
        return results
    
    def _get_bus_results(self) -> List[Dict]:
        """获取母线电压结果
        
        Returns:
            List[Dict]: 母线结果列表
        """
        results = []
        if len(self.net.res_bus) > 0:
            for idx in self.net.res_bus.index:
                bus_info = {
                    "母线ID": int(idx),
                    "名称": self.net.bus.loc[idx, "name"],
                    "电压幅值(pu)": round(self.net.res_bus.loc[idx, "vm_pu"], 4),
                    "电压角度(度)": round(self.net.res_bus.loc[idx, "va_degree"], 4),
                    "电压越限": self._check_voltage_violation(
                        self.net.res_bus.loc[idx, "vm_pu"]
                    ),
                }
                results.append(bus_info)
        return results
    
    def _get_gen_results(self) -> List[Dict]:
        """获取发电机输出结果
        
        Returns:
            List[Dict]: 发电机结果列表
        """
        results = []
        if len(self.net.res_gen) > 0:
            for idx in self.net.res_gen.index:
                gen_info = {
                    "发电机ID": int(idx),
                    "名称": self.net.gen.loc[idx, "name"],
                    "有功输出(MW)": round(self.net.res_gen.loc[idx, "p_mw"], 4),
                    "无功输出(MVar)": round(self.net.res_gen.loc[idx, "q_mvar"], 4),
                }
                results.append(gen_info)
        # 包含ext_grid
        if len(self.net.res_ext_grid) > 0:
            for idx in self.net.res_ext_grid.index:
                gen_info = {
                    "发电机ID": f"ext_grid_{int(idx)}",
                    "名称": self.net.ext_grid.loc[idx, "name"],
                    "有功输出(MW)": round(self.net.res_ext_grid.loc[idx, "p_mw"], 4),
                    "无功输出(MVar)": round(self.net.res_ext_grid.loc[idx, "q_mvar"], 4),
                }
                results.append(gen_info)
        return results
    
    def _get_load_results(self) -> List[Dict]:
        """获取负载功率结果
        
        Returns:
            List[Dict]: 负载结果列表
        """
        results = []
        if len(self.net.res_load) > 0:
            for idx in self.net.res_load.index:
                load_info = {
                    "负载ID": int(idx),
                    "名称": self.net.load.loc[idx, "name"],
                    "有功功率(MW)": round(self.net.res_load.loc[idx, "p_mw"], 4),
                    "无功功率(MVar)": round(self.net.res_load.loc[idx, "q_mvar"], 4),
                }
                results.append(load_info)
        return results
    
    def _check_voltage_violation(self, vm_pu: float, 
                                   vmin_pu: float = 0.95, 
                                   vmax_pu: float = 1.05) -> str:
        """检查电压是否越限
        
        Args:
            vm_pu: 电压幅值(pu)
            vmin_pu: 电压下限
            vmax_pu: 电压上限
        
        Returns:
            str: 越限状态描述
        """
        if vm_pu < vmin_pu:
            return f"越下限({vm_pu:.4f} < {vmin_pu})"
        elif vm_pu > vmax_pu:
            return f"越上限({vm_pu:.4f} > {vmax_pu})"
        else:
            return "正常"
    
    def _calculate_overall_metrics(self) -> Dict:
        """计算综合指标
        
        Returns:
            Dict: 综合指标
        """
        metrics = {}
        
        # 总有功损耗
        total_ploss = 0
        if len(self.net.res_line) > 0:
            ploss_col = "ploss_mw"
            if ploss_col in self.net.res_line.columns:
                total_ploss += self.net.res_line[ploss_col].sum()
            elif "p_loss_mw" in self.net.res_line.columns:
                total_ploss += self.net.res_line["p_loss_mw"].sum()
        if len(self.net.res_trafo) > 0:
            ploss_col = "ploss_mw"
            if ploss_col in self.net.res_trafo.columns:
                total_ploss += self.net.res_trafo[ploss_col].sum()
            elif "p_loss_mw" in self.net.res_trafo.columns:
                total_ploss += self.net.res_trafo["p_loss_mw"].sum()
        metrics["总有功损耗(MW)"] = round(total_ploss, 4)
        
        # 平均电压
        if len(self.net.res_bus) > 0:
            metrics["平均电压(pu)"] = round(self.net.res_bus["vm_pu"].mean(), 4)
            metrics["最低电压(pu)"] = round(self.net.res_bus["vm_pu"].min(), 4)
            metrics["最高电压(pu)"] = round(self.net.res_bus["vm_pu"].max(), 4)
        
        # 线路最大负载率
        if len(self.net.res_line) > 0:
            loading_col = "loading_percent"
            if loading_col in self.net.res_line.columns:
                metrics["线路最大负载率(%)"] = round(
                    self.net.res_line[loading_col].max(), 2
                )
        
        # 变压器最大负载率
        if len(self.net.res_trafo) > 0:
            loading_col = "loading_percent"
            if loading_col in self.net.res_trafo.columns:
                metrics["变压器最大负载率(%)"] = round(
                    self.net.res_trafo[loading_col].max(), 2
                )
        
        return metrics
    
    def run_n1_security_check(self, 
                              element_type: str = "line",
                              max_iterations: int = 30,
                              element_ids: List[int] = None) -> Dict:
        """执行N-1静态安全校核
        
        Args:
            element_type: 故障元件类型 (line, trafo, bus)
            max_iterations: 最大迭代次数
            element_ids: 指定校核的元件索引列表(可选)；为空则校核全部
        
        Returns:
            Dict: N-1校核结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            # 先运行基准潮流
            pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "基准潮流计算不收敛，无法进行N-1校核"}
            
            n1_results = []
            total_elements = 0
            successful_outages = 0
            failed_outages = 0
            voltage_violations = 0
            overload_violations = 0
            
            if element_type == "line":
                all_elements = self.net.line.index.tolist()
            elif element_type == "trafo":
                all_elements = self.net.trafo.index.tolist()
            elif element_type == "bus":
                all_elements = self.net.bus.index.tolist()
            else:
                return {"success": False, "message": f"不支持的元件类型: {element_type}"}

            # 若指定了元件列表，仅校核这些元件（并校验存在性）
            if element_ids is not None:
                resolved_ids = []
                for e in element_ids:
                    r = self._resolve_element_id(element_type, e)
                    if r is None:
                        return {"success": False, "message": f"无法解析元件引用: {element_type} '{e}'"}
                    resolved_ids.append(r)
                invalid = [e for e in resolved_ids if e not in all_elements]
                if invalid:
                    return {"success": False, "message": f"以下{element_type} ID不存在: {invalid}"}
                elements = resolved_ids
            else:
                elements = all_elements
            
            total_elements = len(elements)
            
            for elem_id in elements:
                # 创建电网副本
                net_copy = copy.deepcopy(self.net)
                
                # 模拟元件退出
                if element_type == "line":
                    net_copy.line.loc[elem_id, "in_service"] = False
                elif element_type == "trafo":
                    net_copy.trafo.loc[elem_id, "in_service"] = False
                elif element_type == "bus":
                    pp.drop_bus(net_copy, elem_id)
                
                # 运行潮流
                try:
                    pp.runpp(net_copy, max_iteration=max_iterations)
                    
                    if net_copy.converged:
                        successful_outages += 1
                        has_voltage_violation = False
                        has_overload = False
                        
                        # 检查电压越限
                        if len(net_copy.res_bus) > 0:
                            vmin = net_copy.res_bus["vm_pu"].min()
                            vmax = net_copy.res_bus["vm_pu"].max()
                            has_voltage_violation = bool(vmin < 0.95 or vmax > 1.05)
                            if has_voltage_violation:
                                voltage_violations += 1
                        
                        # 检查线路过载
                        if len(net_copy.res_line) > 0:
                            loading_col = "loading_percent"
                            if loading_col in net_copy.res_line.columns:
                                max_loading = net_copy.res_line[loading_col].max()
                                has_overload = bool(max_loading > 100)
                            if has_overload:
                                overload_violations += 1
                        
                        n1_results.append({
                            "故障元件类型": element_type,
                            "故障元件ID": int(elem_id),
                            "故障元件名称": str(self.net[element_type].loc[elem_id, "name"]),
                            "潮流收敛": True,
                            "电压越限": has_voltage_violation,
                            "线路过载": has_overload,
                        })
                    else:
                        failed_outages += 1
                        n1_results.append({
                            "故障元件类型": element_type,
                            "故障元件ID": int(elem_id),
                            "故障元件名称": self.net[element_type].loc[elem_id, "name"],
                            "潮流收敛": False,
                            "说明": "潮流计算不收敛",
                        })
                except Exception as e:
                    failed_outages += 1
                    n1_results.append({
                        "故障元件类型": element_type,
                        "故障元件ID": int(elem_id),
                        "故障元件名称": self.net[element_type].loc[elem_id, "name"],
                        "潮流收敛": False,
                        "说明": str(e),
                    })
            
            # 压缩详细结果：只保留有问题的条目和前5条正常条目
            has_issues = [r for r in n1_results if not r.get("潮流收敛", True) 
                         or r.get("电压越限", False) or r.get("线路过载", False)]
            normal = [r for r in n1_results if r.get("潮流收敛", True) 
                     and not r.get("电压越限", False) and not r.get("线路过载", False)]
            # 问题条目全部保留，正常条目最多保留5条
            compact_results = has_issues + normal[:5]
            
            result = {
                "success": True,
                "message": f"N-1校核完成({element_type})",
                "统计信息": {
                    "元件总数": total_elements,
                    "校核成功数": successful_outages,
                    "校核失败数": failed_outages,
                    "电压越限次数": voltage_violations,
                    "线路过载次数": overload_violations,
                    "安全性评级": self._get_safety_rating(
                        successful_outages, total_elements,
                        voltage_violations, overload_violations
                    ),
                },
                "详细结果": compact_results,
                "说明": f"共{total_elements}条，仅显示有问题的条目和前5条正常条目",
            }
            
            self.results_cache["n1_check"] = result
            return result
            
        except Exception as e:
            return {"success": False, "message": f"N-1校核失败: {str(e)}"}
    
    def _get_safety_rating(self, successful: int, total: int, 
                           v_violations: int, o_violations: int) -> str:
        """获取安全性评级
        
        Args:
            successful: 成功数
            total: 总数
            v_violations: 电压越限数
            o_violations: 过载数
        
        Returns:
            str: 安全性评级
        """
        if total == 0:
            return "无数据"
        
        success_rate = successful / total
        violation_rate = (v_violations + o_violations) / total
        
        if success_rate >= 0.95 and violation_rate == 0:
            return "安全"
        elif success_rate >= 0.80 and violation_rate <= 0.10:
            return "基本安全"
        elif success_rate >= 0.60:
            return "有风险"
        else:
            return "不安全"
    
    def run_short_circuit_analysis(self, 
                                    fault_type: str = "3phase",
                                    bus_id: Optional[int] = None) -> Dict:
        """短路计算分析
        
        Args:
            fault_type: 故障类型 (3phase, 2phase, 1phase)
            bus_id: 故障母线ID，None表示所有母线
        
        Returns:
            Dict: 短路计算结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            # 运行潮流
            pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "潮流计算不收敛"}

            # 补全 pandapower 3.4 短路计算(IEC 60909 模型)所需参数
            self._ensure_short_circuit_params()

            # 故障类型映射：3phase/2phase/1phase -> 3ph/2ph/1ph
            fault_map = {"3phase": "3ph", "3ph": "3ph",
                         "2phase": "2ph", "2ph": "2ph",
                         "1phase": "1ph", "1ph": "1ph"}
            fault = fault_map.get(str(fault_type).lower(), "3ph")

            # 解析故障母线（字符串名称 -> 内部索引）
            target_bus = None
            if bus_id is not None:
                if isinstance(bus_id, int) and bus_id in self.net.bus.index:
                    target_bus = bus_id
                else:
                    target_bus = self._resolve_element_id("bus", bus_id)

            from pandapower.shortcircuit import calc_sc
            import warnings
            with warnings.catch_warnings():
                # 抑制 pandapower 的提示性警告（近端故障不计算非周期/热稳定电流），
                # 不影响 I''k 与短路容量等核心结果。
                warnings.filterwarnings(
                    "ignore",
                    message=".*aperiodic, thermal short-circuit currents.*")
                calc_sc(self.net, bus=target_bus, fault=fault, ip=True, ith=True)

            res = self.net.res_bus_sc

            if target_bus is not None:
                # 单母线
                if target_bus not in res.index:
                    return {"success": False,
                            "message": f"母线 {bus_id} 短路计算结果缺失（可能不在电网中）"}
                row = res.loc[target_bus]
                ikss = float(row.get("ikss_ka", 0.0) or 0.0)
                vn = float(self.net.bus.loc[target_bus, "vn_kv"]) \
                    if target_bus in self.net.bus.index else 1.0
                sc_power = round(3 ** 0.5 * vn * ikss, 2)
                sc_info = {
                    "母线ID": int(target_bus),
                    "母线名称": self.net.bus.loc[target_bus, "name"],
                    "短路类型": fault_type,
                    "起始短路电流I''k(kA)": round(ikss, 3),
                    "峰值电流ip(kA)": round(float(np.nan_to_num(row.get("ip_ka", 0.0) or 0.0)), 3),
                    "热稳定电流Ith(kA)": round(float(np.nan_to_num(row.get("ith_ka", 0.0) or 0.0)), 3),
                    "短路容量(MVA)": sc_power,
                }
                return {
                    "success": True,
                    "message": f"母线{self.net.bus.loc[target_bus, 'name']}短路计算完成",
                    "母线ID": int(target_bus),
                    "短路类型": fault_type,
                    "短路结果": sc_info,
                }

            # 所有母线
            sc_results = []
            for bus_idx in self.net.bus.index:
                try:
                    if bus_idx not in res.index:
                        continue
                    row = res.loc[bus_idx]
                    ikss = float(row.get("ikss_ka", 0.0) or 0.0)
                    vn = float(self.net.bus.loc[bus_idx, "vn_kv"])
                    sc_power = round(3 ** 0.5 * vn * ikss, 2)
                    sc_results.append({
                        "母线ID": int(bus_idx),
                        "母线名称": self.net.bus.loc[bus_idx, "name"],
                        "短路类型": fault_type,
                        "起始短路电流I''k(kA)": round(ikss, 3),
                        "短路容量(MVA)": sc_power,
                    })
                except Exception as e:
                    sc_results.append({
                        "母线ID": int(bus_idx),
                        "母线名称": self.net.bus.loc[bus_idx, "name"],
                        "错误": str(e),
                    })

            return {
                "success": True,
                "message": f"短路计算完成({fault_type})",
                "短路类型": fault_type,
                "母线短路结果": sc_results,
            }
        except Exception as e:
            return {"success": False, "message": f"短路计算失败: {str(e)}"}

    def _ensure_short_circuit_params(self) -> None:
        """补全 pandapower 3.4 短路计算(IEC 60909 模型)所需的元件参数。

        pandapower 3.4 的 calc_sc 要求外部电网提供 s_sc_max_mva / rx_max，
        发电机提供 vn_kv / xdss_pu / rdss_ohm / pg_percent / cos_phi，
        否则会抛出 'module pandapower has no attribute' 之外的数值/属性错误。
        仅在列缺失或为空时填默认值，不覆盖已有用户数据。
        """
        net = self.net
        # 外部电网短路参数
        if "s_sc_max_mva" not in net.ext_grid.columns:
            net.ext_grid["s_sc_max_mva"] = 1000.0
        else:
            net.ext_grid["s_sc_max_mva"] = net.ext_grid["s_sc_max_mva"].fillna(1000.0)
        if "rx_max" not in net.ext_grid.columns:
            net.ext_grid["rx_max"] = 0.1
        else:
            net.ext_grid["rx_max"] = net.ext_grid["rx_max"].fillna(0.1)

        # 发电机短路参数
        gen = net.gen
        if len(gen) == 0:
            return
        if "vn_kv" not in gen.columns:
            net.gen["vn_kv"] = net.bus.loc[gen["bus"].values, "vn_kv"].values
        if "rdss_ohm" not in gen.columns:
            net.gen["rdss_ohm"] = 0.0
        if "xdss_pu" not in gen.columns:
            net.gen["xdss_pu"] = 0.2
        if "pg_percent" not in gen.columns:
            net.gen["pg_percent"] = 0.0
        if "cos_phi" not in gen.columns:
            net.gen["cos_phi"] = 0.95
        # sn_mva 在部分标准算例(case39)中全为 NaN，导致 xdss_pu*vn²/sn_mva 得到 nan。
        # 用额定有功/功率因数回补（sn_mva 列存在但值为空时）。
        if "sn_mva" not in gen.columns:
            net.gen["sn_mva"] = 100.0
        else:
            cos = net.gen["cos_phi"] if "cos_phi" in gen.columns else 0.95
            net.gen["sn_mva"] = net.gen["sn_mva"].fillna(
                (net.gen["max_p_mw"] / cos).fillna(100.0)
            )

        # 零序网络参数（单相接地故障 1ph 必需）。仅对缺失/为空项回补，
        # 已通过 std_type 正确建模的网络不会被覆盖。
        try:
            from pandapower.std_types import add_zero_impedance_parameters
            add_zero_impedance_parameters(net)
        except Exception:
            pass
        # 线路零序阻抗：架空线近似 R0≈3·R1, X0≈3·X1, C0≈2.5·C1
        line = net.line
        if len(line) > 0:
            for col, src, mult in [("r0_ohm_per_km", "r_ohm_per_km", 3.0),
                                   ("x0_ohm_per_km", "x_ohm_per_km", 3.0),
                                   ("c0_nf_per_km", "c_nf_per_km", 2.5)]:
                if col not in line.columns:
                    net.line[col] = line[src] * mult
                else:
                    net.line[col] = line[col].fillna(line[src] * mult)
            if "g0_nf_per_km" not in line.columns:
                net.line["g0_nf_per_km"] = 0.0
            else:
                net.line["g0_nf_per_km"] = line["g0_nf_per_km"].fillna(0.0)
        # 变压器零序参数
        trafo = net.trafo
        if len(trafo) > 0:
            if "vk0_percent" in trafo.columns:
                net.trafo["vk0_percent"] = trafo["vk0_percent"].fillna(trafo["vk_percent"])
            else:
                net.trafo["vk0_percent"] = trafo["vk_percent"]
            if "vkr0_percent" in trafo.columns:
                net.trafo["vkr0_percent"] = trafo["vkr0_percent"].fillna(trafo["vkr_percent"])
            else:
                net.trafo["vkr0_percent"] = trafo["vkr_percent"]
            if "mag0_percent" in trafo.columns:
                net.trafo["mag0_percent"] = trafo["mag0_percent"].fillna(100.0)
            else:
                net.trafo["mag0_percent"] = 100.0
            if "mag0_rx" in trafo.columns:
                net.trafo["mag0_rx"] = trafo["mag0_rx"].fillna(0.0)
            if "si0_hv_partial" in trafo.columns:
                net.trafo["si0_hv_partial"] = trafo["si0_hv_partial"].fillna(0.9)
            if "vector_group" in trafo.columns:
                net.trafo["vector_group"] = trafo["vector_group"].fillna("Dyn")

    def check_voltage_stability(self, max_load_factor: float = 2.0) -> Dict:
        """电压稳定性分析（P-V曲线）
        
        Args:
            max_load_factor: 最大负载倍数
        
        Returns:
            Dict: 电压稳定性结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "潮流计算不收敛"}
            
            # 计算电压稳定裕度
            # 通过逐步增加负载来寻找电压崩溃点
            stability_results = []
            base_loading = 1.0
            step_size = 0.1
            
            for factor in np.arange(1.0, max_load_factor + 0.1, step_size):
                net_test = copy.deepcopy(self.net)
                
                # 增加负载
                if len(net_test.load) > 0:
                    net_test.load["p_mw"] = net_test.load["p_mw"] * factor
                    net_test.load["q_mvar"] = net_test.load["q_mvar"] * factor
                
                try:
                    pp.runpp(net_test)
                    if net_test.converged:
                        min_voltage = net_test.res_bus["vm_pu"].min()
                        stability_results.append({
                            "负载倍数": round(factor, 2),
                            "最小电压(pu)": round(min_voltage, 4),
                            "收敛": True,
                        })
                    else:
                        stability_results.append({
                            "负载倍数": round(factor, 2),
                            "收敛": False,
                        })
                        break
                except:
                    stability_results.append({
                        "负载倍数": round(factor, 2),
                        "收敛": False,
                        "说明": "潮流计算失败",
                    })
                    break
            
            # 计算稳定裕度
            if len(stability_results) > 0:
                last_converged = [r for r in stability_results if r.get("收敛", False)]
                if len(last_converged) > 0:
                    max_factor = last_converged[-1]["负载倍数"]
                    margin = (max_factor - 1.0) * 100
                else:
                    margin = 0
            else:
                margin = 0
            
            result = {
                "success": True,
                "message": "电压稳定性分析完成",
                "稳定裕度(%)": round(margin, 2),
                "P-V曲线数据": stability_results,
                "说明": f"电网可承受最大负载倍数约为 {max_factor:.1f} 倍，稳定裕度 {margin:.1f}%",
            }
            
            self.results_cache["voltage_stability"] = result
            return result
        except Exception as e:
            return {"success": False, "message": f"电压稳定性分析失败: {str(e)}"}
    
    def set_load_scale(self, factor: float = 1.0) -> Dict:
        """按倍率调整所有负荷的有功和无功

        首次调用会保存原始负荷基准值，后续调用都基于该基准值计算，
        避免累积缩放误差。factor=1.0 可恢复原始负荷。

        Args:
            factor: 负荷倍率（1.0=原始值, 2.0=两倍, 4.0=四倍）

        Returns:
            Dict: 调整结果（含调整前后的负荷统计）
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}

        try:
            if len(self.net.load) == 0:
                return {"success": False, "message": "当前电网无负荷"}

            factor = float(factor)
            if factor <= 0:
                return {"success": False, "message": f"倍率必须为正数，当前值: {factor}"}

            if not hasattr(self, "_load_original_p_mw") or self._load_original_p_mw is None:
                self._load_original_p_mw = self.net.load["p_mw"].copy()
                self._load_original_q_mvar = self.net.load["q_mvar"].copy()

            before_p_mw = self.net.load["p_mw"].sum()
            before_q_mvar = self.net.load["q_mvar"].sum()

            self.net.load["p_mw"] = self._load_original_p_mw * factor
            self.net.load["q_mvar"] = self._load_original_q_mvar * factor

            after_p_mw = self.net.load["p_mw"].sum()
            after_q_mvar = self.net.load["q_mvar"].sum()

            return {
                "success": True,
                "message": f"负荷已调整至 {factor} 倍（基准值保持不变）",
                "倍率": factor,
                "负荷数量": len(self.net.load),
                "调整前总有功(MW)": round(before_p_mw, 2),
                "调整后总有功(MW)": round(after_p_mw, 2),
                "调整前总无功(MVar)": round(before_q_mvar, 2),
                "调整后总无功(MVar)": round(after_q_mvar, 2),
            }
        except Exception as e:
            return {"success": False, "message": f"负荷调整失败: {str(e)}"}

    def get_line_overload_summary(self, threshold: float = 80.0, skip_runpp: bool = False) -> Dict:
        """线路过载分析汇总
        
        Args:
            threshold: 过载阈值(%)
            skip_runpp: 是否跳过潮流计算（当已有潮流结果时设为True）
        
        Returns:
            Dict: 过载分析结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            if not skip_runpp:
                pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "潮流计算不收敛"}
            
            overloaded_lines = []
            normal_lines = []
            
            # 确定列名
            loading_col = "loading_percent" if "loading_percent" in self.net.res_line.columns else None
            ploss_col = "ploss_mw" if "ploss_mw" in self.net.res_line.columns else ("p_loss_mw" if "p_loss_mw" in self.net.res_line.columns else None)
            
            if len(self.net.res_line) > 0:
                for idx in self.net.res_line.index:
                    loading = self.net.res_line.loc[idx, loading_col] if loading_col else 0
                    line_info = {
                        "线路ID": int(idx),
                        "名称": self.net.line.loc[idx, "name"],
                        "负载率(%)": round(loading, 2),
                        "有功损失(MW)": round(
                            self.net.res_line.loc[idx, ploss_col] if ploss_col else 0, 4
                        ),
                    }
                    
                    if loading > threshold:
                        overloaded_lines.append(line_info)
                    else:
                        normal_lines.append(line_info)
            
            # 按负载率排序
            overloaded_lines.sort(key=lambda x: x["负载率(%)"], reverse=True)
            
            # 计算统计
            stats = {}
            if loading_col and len(self.net.res_line) > 0:
                stats["最大值(%)"] = round(self.net.res_line[loading_col].max(), 2)
                stats["最小值(%)"] = round(self.net.res_line[loading_col].min(), 2)
                stats["平均值(%)"] = round(self.net.res_line[loading_col].mean(), 2)
            else:
                stats["最大值(%)"] = 0
                stats["最小值(%)"] = 0
                stats["平均值(%)"] = 0
            
            return {
                "success": True,
                "message": "线路过载分析完成",
                "阈值(%)": threshold,
                "总线路数": len(self.net.res_line),
                "过载线路数": len(overloaded_lines),
                "正常线路数": len(normal_lines),
                "过载线路详情": overloaded_lines,
                "线路负载率统计": stats,
            }
        except Exception as e:
            return {"success": False, "message": f"线路过载分析失败: {str(e)}"}
    
    def get_voltage_violation_summary(self, 
                                        vmin_pu: float = 0.95, 
                                        vmax_pu: float = 1.05,
                                        skip_runpp: bool = False) -> Dict:
        """母线电压越限分析汇总
        
        Args:
            vmin_pu: 电压下限
            vmax_pu: 电压上限
            skip_runpp: 是否跳过潮流计算（当已有潮流结果时设为True）
        
        Returns:
            Dict: 电压越限分析结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            if not skip_runpp:
                pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "潮流计算不收敛"}
            
            violated_buses = []
            normal_buses = []
            
            if len(self.net.res_bus) > 0:
                for idx in self.net.res_bus.index:
                    vm_pu = self.net.res_bus.loc[idx, "vm_pu"]
                    bus_info = {
                        "母线ID": int(idx),
                        "名称": self.net.bus.loc[idx, "name"],
                        "电压幅值(pu)": round(vm_pu, 4),
                        "电压角度(度)": round(
                            self.net.res_bus.loc[idx, "va_degree"], 4
                        ),
                    }
                    
                    if vm_pu < vmin_pu:
                        bus_info["越限类型"] = "越下限"
                        bus_info["偏差量"] = round(vmin_pu - vm_pu, 4)
                        violated_buses.append(bus_info)
                    elif vm_pu > vmax_pu:
                        bus_info["越限类型"] = "越上限"
                        bus_info["偏差量"] = round(vm_pu - vmax_pu, 4)
                        violated_buses.append(bus_info)
                    else:
                        normal_buses.append(bus_info)
            
            return {
                "success": True,
                "message": "电压越限分析完成",
                "限值范围(pu)": f"[{vmin_pu}, {vmax_pu}]",
                "总母线数": len(self.net.res_bus),
                "越限母线数": len(violated_buses),
                "正常母线数": len(normal_buses),
                "越限母线详情": violated_buses,
                "电压统计": {
                    "最大值(pu)": round(
                        self.net.res_bus["vm_pu"].max(), 4
                    ) if len(self.net.res_bus) > 0 else 0,
                    "最小值(pu)": round(
                        self.net.res_bus["vm_pu"].min(), 4
                    ) if len(self.net.res_bus) > 0 else 0,
                    "平均值(pu)": round(
                        self.net.res_bus["vm_pu"].mean(), 4
                    ) if len(self.net.res_bus) > 0 else 0,
                },
            }
        except Exception as e:
            return {"success": False, "message": f"电压越限分析失败: {str(e)}"}
    
    def calculate_loss_analysis(self, skip_runpp: bool = False) -> Dict:
        """网损分析计算
        
        Args:
            skip_runpp: 是否跳过潮流计算（当已有潮流结果时设为True）
        
        Returns:
            Dict: 网损分析结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        
        try:
            if not skip_runpp:
                pp.runpp(self.net)
            if not self.net.converged:
                return {"success": False, "message": "潮流计算不收敛"}
            
            # 确定列名
            line_ploss_col = "ploss_mw" if "ploss_mw" in self.net.res_line.columns else ("p_loss_mw" if "p_loss_mw" in self.net.res_line.columns else None)
            line_qloss_col = "qloss_mvar" if "qloss_mvar" in self.net.res_line.columns else ("q_loss_mvar" if "q_loss_mvar" in self.net.res_line.columns else None)
            trafo_ploss_col = "ploss_mw" if "ploss_mw" in self.net.res_trafo.columns else ("p_loss_mw" if "p_loss_mw" in self.net.res_trafo.columns else None)
            trafo_qloss_col = "qloss_mvar" if "qloss_mvar" in self.net.res_trafo.columns else ("q_loss_mvar" if "q_loss_mvar" in self.net.res_trafo.columns else None)
            
            # 线路损耗
            line_loss = 0
            line_loss_detail = []
            if len(self.net.res_line) > 0:
                for idx in self.net.res_line.index:
                    ploss = self.net.res_line.loc[idx, line_ploss_col] if line_ploss_col else 0
                    qloss = self.net.res_line.loc[idx, line_qloss_col] if line_qloss_col else 0
                    line_loss += ploss
                    line_loss_detail.append({
                        "线路ID": int(idx),
                        "名称": self.net.line.loc[idx, "name"],
                        "有功损耗(MW)": round(ploss, 4),
                        "无功损耗(MVar)": round(qloss, 4),
                    })
            
            # 变压器损耗
            trafo_loss = 0
            trafo_loss_detail = []
            if len(self.net.res_trafo) > 0:
                for idx in self.net.res_trafo.index:
                    ploss = self.net.res_trafo.loc[idx, trafo_ploss_col] if trafo_ploss_col else 0
                    qloss = self.net.res_trafo.loc[idx, trafo_qloss_col] if trafo_qloss_col else 0
                    trafo_loss += ploss
                    trafo_loss_detail.append({
                        "变压器ID": int(idx),
                        "名称": self.net.trafo.loc[idx, "name"],
                        "有功损耗(MW)": round(ploss, 4),
                        "无功损耗(MVar)": round(qloss, 4),
                    })
            
            # 计算总供电量
            total_gen = 0
            if len(self.net.res_gen) > 0:
                total_gen += self.net.res_gen["p_mw"].sum()
            if len(self.net.res_ext_grid) > 0:
                total_gen += self.net.res_ext_grid["p_mw"].sum()
            
            total_load = 0
            if len(self.net.res_load) > 0:
                total_load = self.net.res_load["p_mw"].sum()
            
            total_loss = line_loss + trafo_loss
            loss_rate = (total_loss / total_gen * 100) if total_gen > 0 else 0
            
            return {
                "success": True,
                "message": "网损分析完成",
                "总供电功率(MW)": round(total_gen, 4),
                "总负载功率(MW)": round(total_load, 4),
                "总有功损耗(MW)": round(total_loss, 4),
                "线路损耗(MW)": round(line_loss, 4),
                "变压器损耗(MW)": round(trafo_loss, 4),
                "网损率(%)": round(loss_rate, 4),
                "线路损耗详情": line_loss_detail,
                "变压器损耗详情": trafo_loss_detail,
            }
        except Exception as e:
            return {"success": False, "message": f"网损分析失败: {str(e)}"}
    
    # ==================== 扩展工具：拓扑 / 参数 / 知识 / 排序 / 风险 / 运行方式 ====================

    def _bus_name_map(self) -> Dict[int, str]:
        """构建母线ID->名称映射"""
        if self.net is None:
            return {}
        return {int(i): str(n) for i, n in zip(self.net.bus.index, self.net.bus["name"])}

    @staticmethod
    def _norm_element_name(name: str) -> str:
        """归一化元件名称：去空格、中文->英文缩写、转小写，便于模糊匹配"""
        s = str(name).lower().replace(" ", "")
        s = s.replace("母线", "bus").replace("线路", "line").replace("变压器", "trafo")
        s = s.replace("发电机", "gen").replace("外部电网", "ext_grid").replace("负荷", "load")
        s = s.replace("generator", "gen")
        return s

    def _resolve_element_id(self, element_type: str, ref) -> Optional[int]:
        """把用户对元件的引用(名称/中文/编号/第N个)解析为 pandapower 索引

        Args:
            element_type: bus/line/trafo/gen/load/ext_grid
            ref: int 索引、str 名称("Bus 2"/"母线2"/"Line 1-2"/"第3条线路")等

        Returns:
            Optional[int]: 解析到的索引；无法解析返回 None
        """
        df_map = {
            "bus": self.net.bus, "line": self.net.line, "trafo": self.net.trafo,
            "gen": self.net.gen, "load": self.net.load, "ext_grid": self.net.ext_grid,
        }
        if element_type not in df_map or self.net is None:
            return None
        df = df_map[element_type]
        # 直接给出整数索引
        if isinstance(ref, int):
            return ref if ref in df.index else None
        if isinstance(ref, str):
            s = ref.strip()
            # 纯数字：尝试 0-based 索引、1-based 索引（按位置）
            if s.isdigit():
                return self._by_index_or_position(df, int(s))
            # 含中文类型前缀的"类型+序号"引用：如 线路11 / 母线2 / 发电机3 / 变压器1 / 负荷5
            # 注意：仅当中文字符出现时才按序号解析，避免把英文名 "Line 1-2" 误判为序号2
            import re
            has_cjk_type = any(t in s for t in ("线路", "母线", "变压器", "发电机", "负荷",
                                                 "线", "母", "变", "机", "载"))
            nums = re.findall(r"\d+", s)
            if has_cjk_type and nums:
                r = self._by_index_or_position(df, int(nums[-1]))
                if r is not None:
                    return r
            target = self._norm_element_name(s)
            # 精确匹配名称
            for i in df.index:
                if self._norm_element_name(df.loc[i, "name"]) == target:
                    return int(i)
            # 包含匹配（如 "线路1-2" 命中 "Line 1-2"）
            if target:
                for i in df.index:
                    if target in self._norm_element_name(df.loc[i, "name"]):
                        return int(i)
            # "第N条/第N个/第N台"
            m = re.search(r"第\s*(\d+)\s*(个|条|台|座)?", s)
            if m:
                n = int(m.group(1))
                if 0 <= n - 1 < len(df.index):
                    return int(df.index[n - 1])
        return None

    @staticmethod
    def _by_index_or_position(df, n: int) -> Optional[int]:
        """把序号 n 解析为 pandas 索引：优先 0-based 索引，其次 1-based，再次按位置取第 n 个。"""
        if n in df.index:
            return int(n)
        if (n - 1) in df.index:
            return int(n - 1)
        if 0 <= n - 1 < len(df.index):
            return int(df.index[n - 1])
        return None

    def get_grid_topology(self) -> Dict:
        """获取电网拓扑结构（分析对象维度）

        Returns:
            Dict: 电网拓扑信息（母线、线路连接、变压器、发电机、负荷等）
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            bmap = self._bus_name_map()
            bus_list = []
            for i in self.net.bus.index:
                bus_list.append({
                    "母线ID": int(i),
                    "名称": self.net.bus.loc[i, "name"],
                    "电压等级(kV)": round(float(self.net.bus.loc[i, "vn_kv"]), 2),
                })
            line_list = []
            for i in self.net.line.index:
                line_list.append({
                    "线路ID": int(i),
                    "名称": self.net.line.loc[i, "name"],
                    "起始母线": bmap.get(int(self.net.line.loc[i, "from_bus"]), "?"),
                    "终止母线": bmap.get(int(self.net.line.loc[i, "to_bus"]), "?"),
                    "长度(km)": round(float(self.net.line.loc[i, "length_km"]), 2),
                })
            trafo_list = []
            for i in self.net.trafo.index:
                trafo_list.append({
                    "变压器ID": int(i),
                    "名称": self.net.trafo.loc[i, "name"],
                    "高压侧母线": bmap.get(int(self.net.trafo.loc[i, "hv_bus"]), "?"),
                    "低压侧母线": bmap.get(int(self.net.trafo.loc[i, "lv_bus"]), "?"),
                })
            gen_list = []
            for i in self.net.gen.index:
                gen_list.append({
                    "发电机ID": int(i),
                    "名称": self.net.gen.loc[i, "name"],
                    "所在母线": bmap.get(int(self.net.gen.loc[i, "bus"]), "?"),
                    "有功设定(MW)": round(float(self.net.gen.loc[i, "p_mw"]), 2),
                })
            ext_list = []
            for i in self.net.ext_grid.index:
                ext_list.append({
                    "外部电网ID": int(i),
                    "名称": self.net.ext_grid.loc[i, "name"],
                    "所在母线": bmap.get(int(self.net.ext_grid.loc[i, "bus"]), "?"),
                })
            load_list = []
            for i in self.net.load.index:
                load_list.append({
                    "负荷ID": int(i),
                    "名称": self.net.load.loc[i, "name"],
                    "所在母线": bmap.get(int(self.net.load.loc[i, "bus"]), "?"),
                    "有功(MW)": round(float(self.net.load.loc[i, "p_mw"]), 2),
                })
            return {
                "success": True,
                "message": "电网拓扑获取成功",
                "电网规模": {
                    "母线数": len(bus_list),
                    "线路数": len(line_list),
                    "变压器数": len(trafo_list),
                    "发电机数": len(gen_list),
                    "外部电网数": len(ext_list),
                    "负荷数": len(load_list),
                },
                "母线列表": bus_list,
                "线路连接": line_list,
                "变压器连接": trafo_list,
                "发电机列表": gen_list,
                "外部电网列表": ext_list,
                "负荷列表": load_list,
            }
        except Exception as e:
            return {"success": False, "message": f"获取拓扑失败: {str(e)}"}

    def list_grid_elements(self, element_type: str = "all") -> Dict:
        """列出电网中的元件（分析对象维度）

        Args:
            element_type: bus/line/trafo/gen/load/ext_grid/all

        Returns:
            Dict: 元件清单
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            bmap = self._bus_name_map()
            allowed = {
                "bus": self.net.bus, "line": self.net.line, "trafo": self.net.trafo,
                "gen": self.net.gen, "load": self.net.load, "ext_grid": self.net.ext_grid,
            }
            if element_type != "all" and element_type not in allowed:
                return {"success": False, "message": f"不支持的元件类型: {element_type}"}
            result = {"success": True, "message": "元件清单获取成功", "元件列表": {}}
            for et, df in allowed.items():
                if element_type != "all" and et != element_type:
                    continue
                items = []
                for i in df.index:
                    item = {"ID": int(i), "名称": str(df.loc[i, "name"])}
                    if et == "line":
                        item["连接"] = f"{bmap.get(int(df.loc[i, 'from_bus']), '?')} -> {bmap.get(int(df.loc[i, 'to_bus']), '?')}"
                    elif et == "trafo":
                        item["连接"] = f"{bmap.get(int(df.loc[i, 'hv_bus']), '?')} / {bmap.get(int(df.loc[i, 'lv_bus']), '?')}"
                    elif et in ("gen", "load", "ext_grid"):
                        item["所在母线"] = bmap.get(int(df.loc[i, "bus"]), "?")
                    elif et == "bus":
                        item["电压等级(kV)"] = round(float(df.loc[i, "vn_kv"]), 2)
                    items.append(item)
                result["元件列表"][et] = items
            return result
        except Exception as e:
            return {"success": False, "message": f"列出元件失败: {str(e)}"}

    def get_element_params(self, element_type: str, element_id: int) -> Dict:
        """获取指定元件的参数（元件参数维度）

        Args:
            element_type: bus/line/trafo/gen/load/ext_grid
            element_id: 元件在 pandapower 中的索引

        Returns:
            Dict: 元件参数
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            bmap = self._bus_name_map()
            df_map = {
                "bus": self.net.bus, "line": self.net.line, "trafo": self.net.trafo,
                "gen": self.net.gen, "load": self.net.load, "ext_grid": self.net.ext_grid,
            }
            if element_type not in df_map:
                return {"success": False, "message": f"不支持的元件类型: {element_type}"}
            df = df_map[element_type]
            resolved = self._resolve_element_id(element_type, element_id)
            if resolved is None:
                return {"success": False,
                        "message": f"无法解析元件引用: {element_type} '{element_id}'"
                                   f"（系统共 {len(df.index)} 个{element_type}，"
                                   f"可用编号 0~{len(df.index)-1} 或 1~{len(df.index)}）"}
            element_id = resolved
            if element_id not in df.index:
                return {"success": False, "message": f"未找到 {element_type} ID={element_id} 的元件"}
            row = df.loc[element_id]
            params = {"元件类型": element_type, "元件ID": int(element_id), "名称": str(row.get("name", ""))}
            if element_type == "bus":
                params["电压等级(kV)"] = round(float(row.get("vn_kv", 0)), 2)
                if "type" in df.columns:
                    params["类型"] = str(row.get("type", ""))
                if "max_vm_pu" in df.columns:
                    params["电压上限(pu)"] = float(row.get("max_vm_pu", 0))
                if "min_vm_pu" in df.columns:
                    params["电压下限(pu)"] = float(row.get("min_vm_pu", 0))
            elif element_type == "line":
                params["起始母线"] = bmap.get(int(row.get("from_bus", -1)), "?")
                params["终止母线"] = bmap.get(int(row.get("to_bus", -1)), "?")
                params["长度(km)"] = round(float(row.get("length_km", 0)), 2)
                if "std_type" in df.columns and row.get("std_type"):
                    params["标准型号"] = str(row.get("std_type"))
                if "max_i_ka" in df.columns:
                    params["额定载流量(kA)"] = round(float(row.get("max_i_ka", 0)), 4)
                if "r_ohmperkm" in df.columns:
                    params["单位长度电阻(Ω/km)"] = round(float(row.get("r_ohmperkm", 0)), 6)
                if "x_ohmperkm" in df.columns:
                    params["单位长度电抗(Ω/km)"] = round(float(row.get("x_ohmperkm", 0)), 6)
                if "parallel" in df.columns:
                    params["并联数"] = int(row.get("parallel", 1))
                if "in_service" in df.columns:
                    params["是否投运"] = bool(row.get("in_service", True))
            elif element_type == "trafo":
                params["高压侧母线"] = bmap.get(int(row.get("hv_bus", -1)), "?")
                params["低压侧母线"] = bmap.get(int(row.get("lv_bus", -1)), "?")
                if "std_type" in df.columns and row.get("std_type"):
                    params["标准型号"] = str(row.get("std_type"))
                if "s_nva" in df.columns:
                    params["额定容量(MVA)"] = round(float(row.get("s_nva", 0)), 2)
                if "in_service" in df.columns:
                    params["是否投运"] = bool(row.get("in_service", True))
            elif element_type == "gen":
                params["所在母线"] = bmap.get(int(row.get("bus", -1)), "?")
                if "p_mw" in df.columns:
                    params["有功设定(MW)"] = round(float(row.get("p_mw", 0)), 2)
                if "vm_pu" in df.columns:
                    params["电压设定(pu)"] = round(float(row.get("vm_pu", 0)), 4)
                if "controllable" in df.columns:
                    params["可控"] = bool(row.get("controllable", False))
                if "max_p_mw" in df.columns:
                    params["最大有功(MW)"] = round(float(row.get("max_p_mw", 0)), 2)
                if "min_p_mw" in df.columns:
                    params["最小有功(MW)"] = round(float(row.get("min_p_mw", 0)), 2)
                if "in_service" in df.columns:
                    params["是否投运"] = bool(row.get("in_service", True))
            elif element_type == "load":
                params["所在母线"] = bmap.get(int(row.get("bus", -1)), "?")
                if "p_mw" in df.columns:
                    params["有功(MW)"] = round(float(row.get("p_mw", 0)), 2)
                if "q_mvar" in df.columns:
                    params["无功(MVar)"] = round(float(row.get("q_mvar", 0)), 2)
                if "in_service" in df.columns:
                    params["是否投运"] = bool(row.get("in_service", True))
            elif element_type == "ext_grid":
                params["所在母线"] = bmap.get(int(row.get("bus", -1)), "?")
                if "vm_pu" in df.columns:
                    params["电压设定(pu)"] = round(float(row.get("vm_pu", 0)), 4)
                if "va_degree" in df.columns:
                    params["相角(度)"] = round(float(row.get("va_degree", 0)), 4)
            return {"success": True, "message": f"{element_type} 参数获取成功", "参数": params}
        except Exception as e:
            return {"success": False, "message": f"获取元件参数失败: {str(e)}"}

    def query_knowledge(self, topic: str = None) -> Dict:
        """查询电网分析知识/元信息（知识维度）

        Args:
            topic: 知识主题关键词，如 电压范围/N-1/工具/潮流/短路；为空返回全部

        Returns:
            Dict: 知识条目
        """
        try:
            from config import KNOWLEDGE_BASE
            if not topic:
                items = [{"key": k, **v} for k, v in KNOWLEDGE_BASE.items()]
                return {"success": True, "message": "已返回全部知识条目", "知识条目": items}
            topic_lower = topic.strip().lower()
            matched_keys = []
            scored = []
            if topic_lower in KNOWLEDGE_BASE:
                scored.append((0, topic_lower))  # 精确键名，最高优先级
            else:
                # 容错匹配：支持中文别名、双向子串、标题/正文关键词；并按相关度排序
                for k, v in KNOWLEDGE_BASE.items():
                    aliases = [str(a).lower() for a in v.get("aliases", [])]
                    title = v.get("title", "").lower()
                    content = v.get("content", "").lower()
                    hay = (k + " " + title + " " + content + " " + " ".join(aliases)).lower()
                    # 评分：别名精确命中(1) > 标题命中(2) > 正文命中(3)，命中方式越多分越低（越靠前）
                    score = None
                    if topic_lower in aliases:
                        score = 1
                    elif topic_lower in title:
                        score = 2
                    elif (any(a and a in topic_lower for a in aliases)
                          or any(topic_lower and topic_lower in a for a in aliases)
                          or topic_lower in content):
                        score = 3
                    if score is not None and k not in matched_keys:
                        scored.append((score, k))
                        matched_keys.append(k)
            if not scored:
                return {"success": False,
                        "message": f"未找到与'{topic}'相关的知识，可用主题：{', '.join(KNOWLEDGE_BASE.keys())}"}
            scored.sort(key=lambda x: x[0])  # 相关度高的排前面
            matched_keys = [k for _, k in scored]
            matched = [{"key": k, **KNOWLEDGE_BASE[k]} for k in matched_keys]
            return {"success": True, "message": f"找到 {len(matched)} 条相关知识", "知识条目": matched}
        except Exception as e:
            return {"success": False, "message": f"知识查询失败: {str(e)}"}

    def _ensure_power_flow(self) -> bool:
        """确保已运行潮流计算且收敛。

        注意：标准 case39 经由 pp.networks.case39() 创建后可能残留 converged=True
        但 res_bus 尚未计算，因此以 res_bus 是否有效（非空且非全 NaN）作为判断依据，
        避免误判为“已算过”而跳过潮流计算。
        """
        if self.net is None:
            return False
        try:
            res_valid = (hasattr(self.net, "res_bus") and len(self.net.res_bus) > 0
                         and not self.net.res_bus["vm_pu"].isna().all())
            if not res_valid:
                pp.runpp(self.net)
            return bool(self.net.converged)
        except Exception:
            try:
                pp.runpp(self.net)
                return bool(self.net.converged)
            except Exception:
                return False

    def rank_elements(self, element_type: str = "line",
                      metric: str = "loading_percent",
                      top_n: int = 5, order: str = "desc",
                      run_flow: bool = True) -> Dict:
        """按指标对元件排序筛选（筛选范围维度）

        Args:
            element_type: line/trafo/bus
            metric: loading_percent(负载率) / voltage(电压,仅bus) / ploss_mw(有功损耗)
            top_n: 返回前 N 个
            order: desc(从高到低) / asc(从低到高)
            run_flow: 是否先运行潮流计算

        Returns:
            Dict: 排序后的元件列表
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            if run_flow and not self._ensure_power_flow():
                return {"success": False, "message": "潮流计算不收敛，无法排序"}
            bmap = self._bus_name_map()
            if element_type == "line":
                res, df = self.net.res_line, self.net.line
                name_of = lambda i: df.loc[i, "name"]
            elif element_type == "trafo":
                res, df = self.net.res_trafo, self.net.trafo
                name_of = lambda i: df.loc[i, "name"]
            elif element_type == "bus":
                res, df = self.net.res_bus, self.net.bus
                name_of = lambda i: df.loc[i, "name"]
            else:
                return {"success": False, "message": f"不支持的排序对象: {element_type}"}
            if len(res) == 0:
                return {"success": False, "message": f"{element_type} 无计算结果"}
            if metric == "voltage" and element_type == "bus":
                col, unit = "vm_pu", "pu"
            elif metric == "ploss_mw":
                col = "ploss_mw" if "ploss_mw" in res.columns else ("p_loss_mw" if "p_loss_mw" in res.columns else None)
                unit = "MW"
            elif metric == "loading_percent":
                col = "loading_percent" if "loading_percent" in res.columns else ("loading" if "loading" in res.columns else None)
                unit = "%"
            else:
                return {"success": False, "message": f"不支持的指标: {metric}"}
            if col is None:
                return {"success": False, "message": f"结果中无指标列: {metric}"}
            rows = []
            for i in res.index:
                val = float(res.loc[i, col])
                if element_type == "bus":
                    lab = bmap.get(int(i), name_of(i))
                elif element_type == "line":
                    lab = f"{name_of(i)} ({bmap.get(int(df.loc[i, 'from_bus']), '?')}->{bmap.get(int(df.loc[i, 'to_bus']), '?')})"
                else:
                    lab = f"{name_of(i)} ({bmap.get(int(df.loc[i, 'hv_bus']), '?')}/{bmap.get(int(df.loc[i, 'lv_bus']), '?')})"
                rows.append({"ID": int(i), "名称": lab, "指标值": round(val, 4), "单位": unit})
            rows.sort(key=lambda x: x["指标值"], reverse=(order == "desc"))
            top = rows[:max(1, int(top_n))]
            return {
                "success": True,
                "message": f"{element_type} 按 {metric}({order}) 排序前 {len(top)} 项",
                "排序对象": element_type, "指标": metric, "单位": unit, "顺序": order,
                "排名结果": top,
            }
        except Exception as e:
            return {"success": False, "message": f"排序失败: {str(e)}"}

    def analyze_element_security(self, element_type: str, element_id: int,
                                 max_iterations: int = 30) -> Dict:
        """对单一指定元件做 N-1 安全分析（元件维度）

        Args:
            element_type: line/trafo/bus
            element_id: 元件索引
            max_iterations: 最大迭代次数

        Returns:
            Dict: 该元件开断后的安全性分析（含电压越限、过载证据）
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            if element_type not in ("line", "trafo", "bus"):
                return {"success": False, "message": f"不支持的元件类型: {element_type}"}
            df = {"line": self.net.line, "trafo": self.net.trafo, "bus": self.net.bus}[element_type]
            resolved = self._resolve_element_id(element_type, element_id)
            if resolved is None:
                return {"success": False,
                        "message": f"无法解析元件引用: {element_type} '{element_id}'"
                                   f"（系统共 {len(df.index)} 个{element_type}，"
                                   f"可用编号 0~{len(df.index)-1} 或 1~{len(df.index)}）"}
            element_id = resolved
            if element_id not in df.index:
                return {"success": False, "message": f"未找到 {element_type} ID={element_id}"}
            elem_name = str(df.loc[element_id, "name"])
            if not self._ensure_power_flow():
                return {"success": False, "message": "基准潮流不收敛"}
            net_copy = copy.deepcopy(self.net)
            if element_type == "line":
                net_copy.line.loc[element_id, "in_service"] = False
            elif element_type == "trafo":
                net_copy.trafo.loc[element_id, "in_service"] = False
            else:
                pp.drop_bus(net_copy, element_id)
            try:
                pp.runpp(net_copy, max_iteration=max_iterations)
            except Exception as e:
                return {"success": True, "message": f"元件 {elem_name} 开断后潮流不收敛",
                        "故障元件": elem_name, "潮流收敛": False, "安全": False,
                        "说明": f"开断后系统失稳/不收敛: {str(e)}"}
            if not net_copy.converged:
                return {"success": True, "message": f"元件 {elem_name} 开断后潮流不收敛",
                        "故障元件": elem_name, "潮流收敛": False, "安全": False}
            bmap = self._bus_name_map()
            v_viol, o_viol = [], []
            if len(net_copy.res_bus) > 0:
                for i in net_copy.res_bus.index:
                    vm = float(net_copy.res_bus.loc[i, "vm_pu"])
                    if vm < 0.95 or vm > 1.05:
                        v_viol.append({"母线": bmap.get(int(i), str(i)),
                                       "电压(pu)": round(vm, 4),
                                       "类型": "越下限" if vm < 0.95 else "越上限"})
            loading_col = "loading_percent" if "loading_percent" in net_copy.res_line.columns else None
            if loading_col and len(net_copy.res_line) > 0:
                for i in net_copy.res_line.index:
                    ld = float(net_copy.res_line.loc[i, loading_col])
                    if ld > 100.0:
                        o_viol.append({"线路": str(net_copy.line.loc[i, "name"]),
                                       "负载率(%)": round(ld, 2)})
            safe = (len(v_viol) == 0 and len(o_viol) == 0)
            return {
                "success": True,
                "message": f"元件 {elem_name} 开断后{'安全' if safe else '存在越限/过载'}",
                "故障元件": elem_name, "潮流收敛": True, "安全": safe,
                "电压越限数": len(v_viol), "过载数": len(o_viol),
                "电压越限证据": v_viol, "过载证据": o_viol,
            }
        except Exception as e:
            return {"success": False, "message": f"单元件安全分析失败: {str(e)}"}

    def generate_risk_report(self, vmin_pu: float = 0.95, vmax_pu: float = 1.05,
                             overload_threshold: float = 100.0, top_n: int = 5) -> Dict:
        """生成电网风险报告（风险+证据维度）

        Args:
            vmin_pu/vmax_pu: 电压允许范围
            overload_threshold: 线路/变压器过载阈值(%)
            top_n: 风险项最多展示数

        Returns:
            Dict: 风险报告，含电压越限、过载证据与建议
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            if not self._ensure_power_flow():
                return {"success": False, "message": "潮流计算不收敛，无法生成风险报告"}
            bmap = self._bus_name_map()
            risk_items = []
            v_viol = []
            for i in self.net.res_bus.index:
                vm = float(self.net.res_bus.loc[i, "vm_pu"])
                if vm < vmin_pu or vm > vmax_pu:
                    v_viol.append({"母线": bmap.get(int(i), str(i)),
                                   "电压(pu)": round(vm, 4),
                                   "类型": "越下限" if vm < vmin_pu else "越上限",
                                   "偏差": round(abs(vm - (vmin_pu if vm < vmin_pu else vmax_pu)), 4)})
            for v in v_viol:
                risk_items.append({"风险类型": "电压越限", "对象": v["母线"], "证据": v})
            loading_col = "loading_percent" if "loading_percent" in self.net.res_line.columns else ("loading" if "loading" in self.net.res_line.columns else None)
            line_ov = []
            if loading_col:
                for i in self.net.res_line.index:
                    ld = float(self.net.res_line.loc[i, loading_col])
                    if ld > overload_threshold:
                        line_ov.append({"线路": str(self.net.line.loc[i, "name"]),
                                        "连接": f"{bmap.get(int(self.net.line.loc[i, 'from_bus']), '?')}->{bmap.get(int(self.net.line.loc[i, 'to_bus']), '?')}",
                                        "负载率(%)": round(ld, 2)})
            for l in line_ov:
                risk_items.append({"风险类型": "线路过载", "对象": l["线路"], "证据": l})
            trafo_ov = []
            if loading_col and len(self.net.res_trafo) > 0:
                for i in self.net.res_trafo.index:
                    ld = float(self.net.res_trafo.loc[i, loading_col])
                    if ld > overload_threshold:
                        trafo_ov.append({"变压器": str(self.net.trafo.loc[i, "name"]),
                                         "负载率(%)": round(ld, 2)})
            for t in trafo_ov:
                risk_items.append({"风险类型": "变压器过载", "对象": t["变压器"], "证据": t})
            total_risk = len(risk_items)
            level = "安全" if total_risk == 0 else ("有风险" if total_risk <= 3 else "高风险")
            suggest = "当前运行方式下未发现越限/过载，电网运行正常。" if total_risk == 0 else \
                f"发现 {total_risk} 项风险，建议优先关注负载率最高的线路与电压越限母线，必要时调整发电出力或转移负荷。"
            return {
                "success": True,
                "message": f"风险报告生成完成，共 {total_risk} 项风险",
                "风险等级": level,
                "风险总数": total_risk,
                "电压越限数": len(v_viol),
                "线路过载数": len(line_ov),
                "变压器过载数": len(trafo_ov),
                "风险明细(前{})".format(top_n): risk_items[:max(1, int(top_n))],
                "运行建议": suggest,
            }
        except Exception as e:
            return {"success": False, "message": f"生成风险报告失败: {str(e)}"}

    def analyze_with_outage(self, element_type: str, element_ids: List[int],
                            analysis: str = "power_flow",
                            vmin_pu: float = 0.95, vmax_pu: float = 1.05,
                            overload_threshold: float = 100.0) -> Dict:
        """在指定元件退出的运行方式下做分析（运行方式维度）

        Args:
            element_type: line/trafo/bus
            element_ids: 需退出的元件索引列表
            analysis: power_flow(潮流) / voltage_violation(电压越限) / line_overload(线路过载)
            vmin_pu/vmax_pu/overload_threshold: 分析参数

        Returns:
            Dict: 检修/退出运行方式下的分析结果
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}
        try:
            if element_type not in ("line", "trafo", "bus"):
                return {"success": False, "message": f"不支持的元件类型: {element_type}"}
            df = {"line": self.net.line, "trafo": self.net.trafo, "bus": self.net.bus}[element_type]
            resolved_ids = []
            for eid in element_ids:
                r = self._resolve_element_id(element_type, eid)
                if r is None:
                    return {"success": False, "message": f"无法解析元件引用: {element_type} '{eid}'"}
                resolved_ids.append(r)
            element_ids = resolved_ids
            for eid in element_ids:
                if eid not in df.index:
                    return {"success": False, "message": f"未找到 {element_type} ID={eid}"}
            net_copy = copy.deepcopy(self.net)
            names = []
            for eid in element_ids:
                names.append(str(df.loc[eid, "name"]))
                if element_type == "bus":
                    pp.drop_bus(net_copy, eid)
                else:
                    net_copy[element_type].loc[eid, "in_service"] = False
            try:
                pp.runpp(net_copy)
            except Exception as e:
                return {"success": False, "message": f"退出 {','.join(names)} 后潮流不收敛: {str(e)}"}
            if not net_copy.converged:
                return {"success": False, "message": f"退出 {','.join(names)} 后潮流不收敛"}
            bmap = {int(i): str(n) for i, n in zip(net_copy.bus.index, net_copy.bus["name"])}
            res = {"success": True, "message": f"已退出[{','.join(names)}]的运行方式下分析完成",
                   "退出元件": names, "分析类型": analysis, "潮流收敛": True}
            if analysis == "power_flow":
                metrics = {}
                if len(net_copy.res_bus) > 0:
                    metrics["最低电压(pu)"] = round(float(net_copy.res_bus["vm_pu"].min()), 4)
                    metrics["最高电压(pu)"] = round(float(net_copy.res_bus["vm_pu"].max()), 4)
                loading_col = "loading_percent" if "loading_percent" in net_copy.res_line.columns else None
                if loading_col and len(net_copy.res_line) > 0:
                    metrics["线路最大负载率(%)"] = round(float(net_copy.res_line[loading_col].max()), 2)
                res["综合指标"] = metrics
            elif analysis == "voltage_violation":
                viol = []
                for i in net_copy.res_bus.index:
                    vm = float(net_copy.res_bus.loc[i, "vm_pu"])
                    if vm < vmin_pu or vm > vmax_pu:
                        viol.append({"母线": bmap.get(int(i), str(i)), "电压(pu)": round(vm, 4),
                                     "类型": "越下限" if vm < vmin_pu else "越上限"})
                res["越限母线数"] = len(viol)
                res["越限母线"] = viol
            elif analysis == "line_overload":
                ov = []
                loading_col = "loading_percent" if "loading_percent" in net_copy.res_line.columns else None
                if loading_col:
                    for i in net_copy.res_line.index:
                        ld = float(net_copy.res_line.loc[i, loading_col])
                        if ld > overload_threshold:
                            ov.append({"线路": str(net_copy.line.loc[i, "name"]), "负载率(%)": round(ld, 2)})
                res["过载线路数"] = len(ov)
                res["过载线路"] = ov
            else:
                return {"success": False, "message": f"不支持的分析类型: {analysis}"}
            return res
        except Exception as e:
            return {"success": False, "message": f"运行方式分析失败: {str(e)}"}

    def get_all_tools(self) -> List[Dict]:
        """获取所有可用工具信息

        Returns:
            List[Dict]: 工具列表
        """
        tools = [
            {
                "name": "create_test_grid",
                "description": "创建测试电网模型",
                "parameters": {
                    "grid_type": "str - 电网类型(case9/case14/case30/case39/case57/case118/case300/simple)"
                },
                "returns": "Dict - 创建结果"
            },
            {
                "name": "run_ac_power_flow",
                "description": "运行交流潮流计算",
                "parameters": {},
                "returns": "Dict - 潮流计算结果，包含线路、变压器、母线、发电机等潮流数据"
            },
            {
                "name": "run_n1_security_check",
                "description": "执行N-1静态安全校核",
                "parameters": {
                    "element_type": "str - 故障元件类型(line/trafo/bus)"
                },
                "returns": "Dict - N-1校核结果，包含安全性评级"
            },
            {
                "name": "run_short_circuit_analysis",
                "description": "短路计算分析",
                "parameters": {
                    "fault_type": "str - 故障类型(3phase/2phase/1phase)",
                    "bus_id": "int - 故障母线ID(可选)"
                },
                "returns": "Dict - 短路计算结果"
            },
            {
                "name": "check_voltage_stability",
                "description": "电压稳定性分析",
                "parameters": {
                    "max_load_factor": "float - 最大负载倍数"
                },
                "returns": "Dict - 电压稳定性结果，包含稳定裕度和P-V曲线数据"
            },
            {
                "name": "get_line_overload_summary",
                "description": "线路过载分析汇总",
                "parameters": {
                    "threshold": "float - 过载阈值(%)"
                },
                "returns": "Dict - 线路过载分析结果"
            },
            {
                "name": "get_voltage_violation_summary",
                "description": "母线电压越限分析汇总",
                "parameters": {
                    "vmin_pu": "float - 电压下限",
                    "vmax_pu": "float - 电压上限"
                },
                "returns": "Dict - 电压越限分析结果"
            },
            {
                "name": "calculate_loss_analysis",
                "description": "网损分析计算",
                "parameters": {},
                "returns": "Dict - 网损分析结果"
            },
            {
                "name": "get_grid_topology",
                "description": "获取电网拓扑结构（母线/线路/变压器/发电机/负荷连接）",
                "parameters": {},
                "returns": "Dict - 电网拓扑信息"
            },
            {
                "name": "list_grid_elements",
                "description": "列出电网中的元件清单",
                "parameters": {
                    "element_type": "str - 元件类型(bus/line/trafo/gen/load/ext_grid/all，默认all)"
                },
                "returns": "Dict - 元件清单"
            },
            {
                "name": "get_element_params",
                "description": "获取指定元件的参数（电阻/电抗/容量/设定值等）",
                "parameters": {
                    "element_type": "str - 元件类型(bus/line/trafo/gen/load/ext_grid)",
                    "element_id": "int - 元件索引"
                },
                "returns": "Dict - 元件参数"
            },
            {
                "name": "query_knowledge",
                "description": "查询电网分析知识/元信息（电压范围/N-1准则/分析方法/工具总览等）",
                "parameters": {
                    "topic": "str - 知识主题关键词(可选，为空返回全部)"
                },
                "returns": "Dict - 知识条目"
            },
            {
                "name": "rank_elements",
                "description": "按指标对元件排序筛选(Top-N)",
                "parameters": {
                    "element_type": "str - 排序对象(line/trafo/bus)",
                    "metric": "str - 指标(loading_percent/voltage/ploss_mw)",
                    "top_n": "int - 返回前N项(默认5)",
                    "order": "str - desc/asc(默认desc)"
                },
                "returns": "Dict - 排序结果"
            },
            {
                "name": "analyze_element_security",
                "description": "对单一指定元件做N-1安全分析(含越限/过载证据)",
                "parameters": {
                    "element_type": "str - 元件类型(line/trafo/bus)",
                    "element_id": "int - 元件索引"
                },
                "returns": "Dict - 单元件安全分析结果"
            },
            {
                "name": "generate_risk_report",
                "description": "生成电网风险报告(汇总电压越限/线路过载并给出证据与建议)",
                "parameters": {
                    "vmin_pu": "float - 电压下限(默认0.95)",
                    "vmax_pu": "float - 电压上限(默认1.05)",
                    "overload_threshold": "float - 过载阈值%(默认100)",
                    "top_n": "int - 风险明细最多展示(默认5)"
                },
                "returns": "Dict - 风险报告"
            },
            {
                "name": "analyze_with_outage",
                "description": "在指定元件退出的运行方式(检修方式)下做分析",
                "parameters": {
                    "element_type": "str - 元件类型(line/trafo/bus)",
                    "element_ids": "list - 需退出的元件索引列表",
                    "analysis": "str - power_flow/voltage_violation/line_overload"
                },
                "returns": "Dict - 运行方式分析结果"
            },
            {
                "name": "apply_voltage_correction",
                "description": "根据潮流结果自动调整发电机电压设定以消除电压越限",
                "parameters": {
                    "vmin_pu": "float - 电压下限(默认0.95)",
                    "vmax_pu": "float - 电压上限(默认1.05)"
                },
                "returns": "Dict - 电压修正结果，含越限详情和修正操作"
            },
            {
                "name": "set_load_scale",
                "description": "按倍率调整所有负荷的有功和无功（基于原始基准值，避免累积误差）",
                "parameters": {
                    "factor": "float - 负荷倍率（1.0=原始值, 2.0=两倍, 4.0=四倍）"
                },
                "returns": "Dict - 调整结果（含调整前后的负荷统计）"
            },
        ]
        return tools

    def _find_adjacent_gens(self, bus_idx: int) -> List[int]:
        """找到与指定母线电气相邻的发电机/ext_grid 索引列表
        返回正数为 gen 索引，负数为 ext_grid 索引（-1 - e_idx）"""
        adjacent = set()
        if len(self.net.gen) > 0 and len(self.net.line) > 0:
            for line_idx in self.net.line.index:
                fb = self.net.line.loc[line_idx, "from_bus"]
                tb = self.net.line.loc[line_idx, "to_bus"]
                if fb == bus_idx or tb == bus_idx:
                    for g_idx in self.net.gen.index:
                        if self.net.gen.loc[g_idx, "bus"] in (fb, tb):
                            adjacent.add(g_idx)
        if len(self.net.ext_grid) > 0:
            for e_idx in self.net.ext_grid.index:
                if self.net.ext_grid.loc[e_idx, "bus"] == bus_idx:
                    adjacent.add(-1 - e_idx)
        return sorted(adjacent)

    def apply_voltage_correction(self, **kwargs) -> Dict:
        """根据当前潮流结果自动调整发电机电压设定，以消除电压越限

        防震荡策略：
        1. 优先处理数量更多的主导越限类型
        2. 跳过同时关联两种越限的冲突发电机
        3. 每次最多调整 3 台发电机，单步 0.01 pu
        4. 仅对主导类型做调整，待主导消除后再处理次要类型

        Returns:
            Dict: 修正结果，包含越限详情和执行的修正操作
        """
        if self.net is None:
            return {"success": False, "message": "请先创建电网模型"}

        try:
            if not self._ensure_power_flow():
                return {"success": False, "message": "潮流计算不收敛，无法进行电压修正"}

            vmin = kwargs.get("vmin_pu", 0.95)
            vmax = kwargs.get("vmax_pu", 1.05)

            under_violations = []
            over_violations = []
            if len(self.net.res_bus) > 0:
                for idx in self.net.res_bus.index:
                    vm = float(self.net.res_bus.loc[idx, "vm_pu"])
                    if vm < vmin:
                        under_violations.append({
                            "bus_idx": int(idx),
                            "bus_name": str(self.net.bus.loc[idx, "name"]),
                            "type": "越下限",
                            "voltage": round(vm, 4),
                            "deficit": round(vmin - vm, 4),
                        })
                    elif vm > vmax:
                        over_violations.append({
                            "bus_idx": int(idx),
                            "bus_name": str(self.net.bus.loc[idx, "name"]),
                            "type": "越上限",
                            "voltage": round(vm, 4),
                            "deficit": round(vm - vmax, 4),
                        })

            all_violations = under_violations + over_violations

            if not all_violations:
                return {
                    "success": True,
                    "message": "当前无电压越限，无需修正",
                    "修正操作": [],
                    "剩余越限数": 0,
                }

            dominant_type = "under" if len(under_violations) >= len(over_violations) else "over"
            dominant_viols = under_violations if dominant_type == "under" else over_violations
            other_viols = over_violations if dominant_type == "under" else under_violations

            dominant_gens = set()
            for v in dominant_viols:
                for g in self._find_adjacent_gens(v["bus_idx"]):
                    dominant_gens.add(g)

            other_gens = set()
            for v in other_viols:
                for g in self._find_adjacent_gens(v["bus_idx"]):
                    other_gens.add(g)

            conflict_gens = dominant_gens & other_gens
            safe_gens = dominant_gens - conflict_gens

            if not safe_gens and dominant_gens:
                safe_gens = dominant_gens
                conflict_gens = set()

            candidates = []
            for v in sorted(dominant_viols, key=lambda x: -x["deficit"]):
                for g_idx in safe_gens:
                    candidates.append({
                        "violation": v,
                        "gen_idx": g_idx,
                        "direction": "raise" if dominant_type == "under" else "lower",
                    })
                if len(candidates) >= 3:
                    break

            corrections = []
            adjusted = set()
            for cand in candidates[:3]:
                g_idx = cand["gen_idx"]
                if g_idx in adjusted:
                    continue
                adjusted.add(g_idx)
                v = cand["violation"]
                direction = cand["direction"]

                if g_idx >= 0 and g_idx in self.net.gen.index:
                    current_vm = float(self.net.gen.loc[g_idx, "vm_pu"])
                    if direction == "raise":
                        new_vm = min(current_vm + 0.01, 1.10)
                    else:
                        new_vm = max(current_vm - 0.01, 0.90)
                    if new_vm != current_vm:
                        self.net.gen.loc[g_idx, "vm_pu"] = new_vm
                        corrections.append({
                            "元件": str(self.net.gen.loc[g_idx, "name"]),
                            "类型": "发电机",
                            "调整前vm_pu": round(current_vm, 4),
                            "调整后vm_pu": round(new_vm, 4),
                            "触发原因": v["bus_name"] + v["type"],
                            "调整方向": "提高" if direction == "raise" else "降低",
                        })
                elif g_idx < 0:
                    e_idx = -1 - g_idx
                    if e_idx in self.net.ext_grid.index:
                        current_vm = float(self.net.ext_grid.loc[e_idx, "vm_pu"])
                        if direction == "raise":
                            new_vm = min(current_vm + 0.01, 1.10)
                        else:
                            new_vm = max(current_vm - 0.01, 0.90)
                        if new_vm != current_vm:
                            self.net.ext_grid.loc[e_idx, "vm_pu"] = new_vm
                            corrections.append({
                                "元件": str(self.net.ext_grid.loc[e_idx, "name"]),
                                "类型": "外部电网",
                                "调整前vm_pu": round(current_vm, 4),
                                "调整后vm_pu": round(new_vm, 4),
                                "触发原因": v["bus_name"] + v["type"],
                                "调整方向": "提高" if direction == "raise" else "降低",
                            })

            skip_count = len(conflict_gens)
            type_label = "越下限" if dominant_type == "under" else "越上限"
            msg = (f"电压修正完成：检测到 {len(all_violations)} 处越限"
                   f"（越下限{len(under_violations)}处，越上限{len(over_violations)}处），"
                   f"优先修正{type_label}，执行 {len(corrections)} 项调整")
            if skip_count > 0:
                msg += f"（跳过 {skip_count} 台冲突发电机）"

            return {
                "success": True,
                "message": msg,
                "主导类型": type_label,
                "越限母线详情": all_violations,
                "修正操作": corrections,
                "冲突发电机数": skip_count,
                "剩余越限数": len(all_violations),
            }

        except Exception as e:
            return {"success": False, "message": f"电压修正失败: {str(e)}"}

    def execute_tool(self, tool_name: str, **kwargs) -> Dict:
        """执行指定工具
        
        Args:
            tool_name: 工具名称
            **kwargs: 工具参数
        
        Returns:
            Dict: 执行结果
        """
        tool_map = {
            "create_test_grid": self.create_test_grid,
            "run_ac_power_flow": self.run_ac_power_flow,
            "run_n1_security_check": self.run_n1_security_check,
            "run_short_circuit_analysis": self.run_short_circuit_analysis,
            "check_voltage_stability": self.check_voltage_stability,
            "get_line_overload_summary": self.get_line_overload_summary,
            "get_voltage_violation_summary": self.get_voltage_violation_summary,
            "calculate_loss_analysis": self.calculate_loss_analysis,
            "get_grid_topology": self.get_grid_topology,
            "list_grid_elements": self.list_grid_elements,
            "get_element_params": self.get_element_params,
            "query_knowledge": self.query_knowledge,
            "rank_elements": self.rank_elements,
            "analyze_element_security": self.analyze_element_security,
            "generate_risk_report": self.generate_risk_report,
            "analyze_with_outage": self.analyze_with_outage,
            "apply_voltage_correction": self.apply_voltage_correction,
            "set_load_scale": self.set_load_scale,
        }
        
        if tool_name not in tool_map:
            return {
                "success": False,
                "message": f"未知的工具: {tool_name}",
                "可用工具": list(tool_map.keys())
            }
        
        try:
            func = tool_map[tool_name]
            return func(**kwargs)
        except Exception as e:
            return {"success": False, "message": f"工具执行失败: {str(e)}"}