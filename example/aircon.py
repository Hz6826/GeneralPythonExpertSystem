# ./example/aircon.py
"""
# 家用空调不制冷诊断知识库 · aircon_not_cooling

## 用途
把「用户描述的不制冷 / 制冷差」翻译成「最可能的故障根因」。知识库按部件划分：
使用设置 → 室内机 → 室外机与压缩机 → 制冷剂回路，并给出跨部件的链式推理。

适用于分体式家用空调（壁挂机 / 柜机），不覆盖中央空调水系统与多联机。

## 推理方式
每条规则的条件都是 `has_<事实名>`：只要工作记忆里存在同名事实，条件就成立
（事实的 `value` 不参与匹配）。规则分三类：

- **根因规则**（优先级 100）：结论直接是故障根因，例如 `capacitor_failure_confirmed`、
  `refrigerant_leak_confirmed`。
- **链式中间事实**（优先级 60）：结论是中间结论，例如 `compressor_no_start`、
  `cooling_capacity_low`，会被下游规则继续消费。
- **低置信分支**（优先级 50）：需要更多证据才能定论，通常作为排查方向。

所有规则都要求 `aircon_running` 成立 —— 它表示「空调已经开机并在吹风」，
没有它就没有讨论制冷效果的前提。

## 使用步骤
1. 在「知识库」面板选中本示例并点「载入」；
2. 用下面的模板（或自写的事实名）断言观察到的现象；
3. 点「单步」逐条观察规则触发，或点「单步到底 / 运行到底」跑到不动点；
4. 在「推理轨迹」里核对 IF（条件）/ THEN（结论），确认根因。

## 断言语法
一行一条事实，等号后面可以跟值：

```text
aircon_running              # 省略值 → true
outdoor_temp = 38           # 数字
```

## 示例事实模板
点代码块右上角的「一键填入」会**先清空工作记忆**，再把这些事实写进去 ——
相当于一键切换到该故障场景。如果想保留已有事实，请用「批量断言」表单。

### 1. 完全不制冷，外机压缩机不启动

```facts
aircon_running
no_cooling
compressor_not_running
relay_click_no_start
capacitor_fault
```

ODU-101 先得出中间事实 `compressor_no_start`，ODU-201 落到
`capacitor_failure_confirmed`（启动电容失效）；ODU-002 也会给出 `capacitor_failure`。
若同时 `compressor_hot`，则 ODU-202 会给出 `compressor_seized`（压缩机卡缸）。

### 2. 制冷越来越差，细管结霜（缺氟）

```facts
aircon_running
weak_cooling
low_refrigerant
refrigerant_leak_sign
gas_line_frost
```

REF-101 → REF-102 → REF-201，得到 `refrigerant_leak_confirmed`；
REF-001 给出 `refrigerant_shortage`，REF-002 给出 `refrigerant_leak`
（接头有油迹就是泄漏点）。这种情况下不要只补氟，要先找到漏点。

### 3. 制冷差，外机很脏或被遮挡

```facts
aircon_running
weak_cooling
condenser_dirty
high_pressure_high
outdoor_unit_blocked
```

REF-003 给出 `condenser_heat_rejection_poor`（冷凝器散热不良），
REF-004 给出 `outdoor_airflow_blocked`（外机散热空间不足）。

### 4. 吹出来是自然风（模式设错）

```facts
aircon_running
no_cooling
mode_set_heat
```

SET-001 给出 `wrong_mode` —— 先确认遥控器模式，再看别的。

### 5. 内机风明显变小

```facts
aircon_running
weak_cooling
filter_dirty
indoor_fan_weak
```

IDU-001 给出 `filter_clogged`，IDU-101 → IDU-201 得到 `indoor_airflow_problem`
（滤网与风量双重问题）。

### 6. 压缩机频繁启停

```facts
aircon_running
compressor_short_cycle
temperature_sensor_fault
```

IDU-004 给出 `room_sensor_fault`（室温传感器异常导致误判达到设定温度）。
"""
import copy

from core.model import Fact, KnowledgeBase, Rule

__name__ = "aircon_not_cooling"

def _has(name):
    """条件：工作内存中存在指定事实。函数名带上事实名，便于静态追踪推理链。"""

    def condition(wm):
        return any(f.name == name for f in wm.facts)

    condition.__name__ = f"has_{name}"
    condition.__qualname__ = f"has_{name}"
    return condition


_kb = KnowledgeBase()

def get_kb():
    return copy.deepcopy(_kb)

# ===================== 使用与设置 =====================
_kb.add_rule(Rule("SET-001 模式设置错误（制热/送风）", [_has("aircon_running"), _has("no_cooling"), _has("mode_set_heat")], Fact("wrong_mode"), 100))                 # fix_switch_to_cool_mode
_kb.add_rule(Rule("SET-002 温度设定高于室温", [_has("aircon_running"), _has("weak_cooling"), _has("thermostat_set_wrong")], Fact("thermostat_misconfigured"), 100))      # fix_set_target_temperature
_kb.add_rule(Rule("SET-003 出风口被家具遮挡", [_has("aircon_running"), _has("weak_cooling"), _has("airflow_short_cycle")], Fact("airflow_blocked"), 50))               # fix_clear_air_outlet

# ===================== 室内机 =====================
_kb.add_rule(Rule("IDU-001 滤网堵塞", [_has("aircon_running"), _has("weak_cooling"), _has("filter_dirty")], Fact("filter_clogged"), 100))                              # fix_clean_air_filter
_kb.add_rule(Rule("IDU-002 内机风量不足", [_has("aircon_running"), _has("indoor_fan_weak")], Fact("indoor_airflow_weak"), 50))                                        # fix_check_indoor_fan_capacitor
_kb.add_rule(Rule("IDU-003 蒸发器结霜", [_has("aircon_running"), _has("weak_cooling"), _has("indoor_coil_icing")], Fact("evaporator_icing"), 100))                   # fix_defrost_and_check_refrigerant
_kb.add_rule(Rule("IDU-004 室温传感器异常", [_has("aircon_running"), _has("compressor_short_cycle"), _has("temperature_sensor_fault")], Fact("room_sensor_fault"), 100))  # fix_replace_room_sensor
_kb.add_rule(Rule("IDU-005 冷凝水排水不畅", [_has("aircon_running"), _has("drainage_blocked")], Fact("drainage_issue"), 50))                                          # fix_clear_drain_pipe

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("IDU-101 中间事实：室内换热不良", [_has("aircon_running"), _has("filter_dirty"), _has("indoor_fan_weak")], Fact("indoor_heat_exchange_poor"), 60))      # 下游：风量问题

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("IDU-201 滤网与风量双重问题（链式）", [_has("aircon_running"), _has("indoor_heat_exchange_poor"), _has("weak_cooling")], Fact("indoor_airflow_problem"), 100))  # fix_service_indoor_unit

# ===================== 室外机与压缩机 =====================
_kb.add_rule(Rule("ODU-001 室外机未通电或未启动", [_has("aircon_running"), _has("no_cooling"), _has("outdoor_unit_not_running")], Fact("outdoor_unit_down"), 100))      # fix_check_outdoor_power_breaker
_kb.add_rule(Rule("ODU-002 启动电容失效", [_has("aircon_running"), _has("compressor_not_running"), _has("capacitor_fault")], Fact("capacitor_failure"), 100))           # fix_replace_run_capacitor
_kb.add_rule(Rule("ODU-003 压缩机热保护动作", [_has("aircon_running"), _has("compressor_not_running"), _has("compressor_hot")], Fact("compressor_thermal_protection"), 100))  # fix_clean_condenser_and_wait_cool
_kb.add_rule(Rule("ODU-004 外机风扇故障", [_has("aircon_running"), _has("outdoor_fan_fault")], Fact("outdoor_fan_failure"), 100))                                      # fix_replace_outdoor_fan_motor
_kb.add_rule(Rule("ODU-005 供电电压偏低", [_has("aircon_running"), _has("compressor_not_running"), _has("power_voltage_low")], Fact("supply_voltage_low"), 50))         # fix_check_power_supply
_kb.add_rule(Rule("ODU-006 四通阀故障", [_has("aircon_running"), _has("no_cooling"), _has("four_way_valve_fault")], Fact("four_way_valve_issue"), 100))               # fix_replace_four_way_valve

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("ODU-101 中间事实：压缩机不启动", [_has("aircon_running"), _has("compressor_not_running"), _has("relay_click_no_start")], Fact("compressor_no_start"), 60))   # 下游：电容 / 卡缸

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("ODU-201 启动电容失效（链式）", [_has("aircon_running"), _has("compressor_no_start"), _has("capacitor_fault")], Fact("capacitor_failure_confirmed"), 100))      # fix_replace_run_capacitor
_kb.add_rule(Rule("ODU-202 压缩机卡缸（链式）", [_has("aircon_running"), _has("compressor_no_start"), _has("compressor_hot")], Fact("compressor_seized"), 100))                 # fix_replace_compressor

# ===================== 制冷剂回路 =====================
_kb.add_rule(Rule("REF-001 制冷剂不足", [_has("aircon_running"), _has("weak_cooling"), _has("low_refrigerant")], Fact("refrigerant_shortage"), 100))                   # fix_check_pressure_and_charge
_kb.add_rule(Rule("REF-002 系统存在泄漏点", [_has("aircon_running"), _has("refrigerant_shortage"), _has("refrigerant_leak_sign")], Fact("refrigerant_leak"), 100))       # fix_find_and_repair_leak
_kb.add_rule(Rule("REF-003 冷凝器散热不良", [_has("aircon_running"), _has("weak_cooling"), _has("condenser_dirty")], Fact("condenser_heat_rejection_poor"), 100))       # fix_clean_condenser_coil
_kb.add_rule(Rule("REF-004 外机散热空间不足", [_has("aircon_running"), _has("high_pressure_high"), _has("outdoor_unit_blocked")], Fact("outdoor_airflow_blocked"), 100))  # fix_remove_obstruction
_kb.add_rule(Rule("REF-005 细管结霜", [_has("aircon_running"), _has("gas_line_frost")], Fact("liquid_line_frost"), 50))                                               # fix_check_throttle_and_charge

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("REF-101 中间事实：制冷循环效率下降", [_has("aircon_running"), _has("weak_cooling"), _has("low_refrigerant")], Fact("cooling_cycle_inefficient"), 60))    # 下游：制冷量

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("REF-102 中间事实：制冷量不足", [_has("aircon_running"), _has("cooling_cycle_inefficient"), _has("gas_line_frost")], Fact("cooling_capacity_low"), 60))     # 下游：泄漏 / 堵塞

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("REF-201 制冷剂泄漏（链式）", [_has("aircon_running"), _has("cooling_capacity_low"), _has("refrigerant_leak_sign")], Fact("refrigerant_leak_confirmed"), 100))  # fix_find_and_repair_leak
_kb.add_rule(Rule("REF-202 系统冰堵或脏堵（链式）", [_has("aircon_running"), _has("cooling_capacity_low"), _has("indoor_coil_icing")], Fact("system_blockage"), 50))             # fix_replace_drier_and_vacuum
