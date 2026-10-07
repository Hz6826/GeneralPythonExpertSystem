# ./example/automotive.py
"""
# 汽车无法启动诊断知识库 · automotive_no_start

## 用途
把「车主描述的启动异常」翻译成「最可能的故障根因」。知识库按系统划分：
电源与起动 → 供油 → 点火 → 进气与配气 → 防盗与电控，并给出跨系统的链式推理。

适用于汽油车「打不着火 / 打火困难」这一类症状，不覆盖行驶中故障与底盘问题。

## 推理方式
每条规则的条件都是 `has_<事实名>`：只要工作记忆里存在同名事实，条件就成立
（事实的 `value` 不参与匹配）。规则分三类：

- **根因规则**（优先级 100）：结论直接是故障根因，例如 `battery_end_of_life`、`fuel_pump_fault`。
- **链式中间事实**（优先级 60）：结论是中间结论，例如 `cranking_power_insufficient`、
  `ignition_energy_weak`，会被下游规则继续消费，形成「现象 → 中间事实 → 根因」的链。
- **低置信分支**（优先级 50 / 10）：需要更多证据才能定论，通常作为排查方向。

所有规则都要求 `car_wont_start` 成立 —— 它是这个场景的入场券。

## 使用步骤
1. 在「知识库」面板选中本示例并点「载入」；
2. 用下面的模板（或自写的事实名）断言观察到的现象；
3. 点「单步」逐条观察规则触发，或点「单步到底 / 运行到底」跑到不动点；
4. 在「推理轨迹」里核对 IF（条件）/ THEN（结论），确认根因。

## 断言语法
一行一条事实，等号后面可以跟值：

```text
car_wont_start              # 省略值 → true
battery_voltage = 11.6      # 数字
```

## 示例事实模板
点代码块右上角的「一键填入」会**先清空工作记忆**，再把这些事实写进去 ——
相当于一键切换到该故障场景。如果想保留已有事实，请用「批量断言」表单。

### 1. 停放一夜后打火无力（电瓶老化）

```facts
car_wont_start
slow_crank
battery_voltage_low
jump_start_ok
battery_old
```

BAT-101 先得出中间事实 `cranking_power_insufficient`，BAT-102 确认故障在电瓶侧，
最后 BAT-201 给出 `battery_end_of_life`。若同时有 `alternator_fault`，
则 BAT-202 会给出 `charging_fault_confirmed`（充电系统导致反复亏电）。

### 2. 只听见"咔哒"一声，起动机不转

```facts
car_wont_start
no_crank
headlights_bright
click_sound_only
```

大灯很亮说明供电正常，于是 START-101 得出 `starter_no_action`，
START-201 落到 `starter_solenoid_fault`（起动机电磁开关只吸不转）。

### 3. 起动机能转但打不着（点火侧）

```facts
car_wont_start
cranks_no_start
spark_weak
spark_plug_fouled
start_then_stall
```

IGN-101 → IGN-102 → IGN-201，得到 `ignition_system_worn`（点火系统老化）；
IGN-001 也会同时给出 `spark_plug_fault`。

### 4. 起动机能转但打不着（供油侧）

```facts
car_wont_start
cranks_no_start
fuel_pressure_low
fuel_filter_clogged
```

FUEL-101 得出 `fuel_supply_insufficient`，FUEL-201 落到 `fuel_filter_blocked`。

### 5. 着车后马上熄火（进气与进气量）

```facts
car_wont_start
start_then_stall
maf_sensor_fault
throttle_body_dirty
```

AIR-002 给出 `maf_fault`（空气流量计故障），AIR-003 给出 `throttle_sticking`（节气门积碳卡滞）。

### 6. 完全没反应且防盗灯常亮

```facts
car_wont_start
cranks_no_start
immobilizer_light_on
```

IMMO-001 给出 `immobilizer_active` —— 钥匙芯片/防盗模块没通过校验，
这种情况不要再反复打火，先检查备用钥匙。
"""
import copy

from core.model import Fact, KnowledgeBase, Rule

__name__ = "automotive_no_start"

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

# ===================== 电源与起动系统 =====================
_kb.add_rule(Rule("PWR-001 电瓶亏电或已老化", [_has("car_wont_start"), _has("no_crank"), _has("battery_voltage_low")], Fact("battery_depleted"), 100))          # fix_charge_or_replace_battery
_kb.add_rule(Rule("PWR-002 电瓶桩头氧化松动", [_has("car_wont_start"), _has("no_crank"), _has("battery_terminal_corroded")], Fact("battery_terminal_poor"), 100))   # fix_clean_battery_terminal
_kb.add_rule(Rule("PWR-003 搭铁线腐蚀", [_has("car_wont_start"), _has("slow_crank"), _has("ground_strap_corroded")], Fact("ground_strap_fault"), 100))             # fix_replace_ground_strap
_kb.add_rule(Rule("PWR-004 发电机不充电", [_has("car_wont_start"), _has("battery_voltage_low"), _has("alternator_fault")], Fact("charging_system_fault"), 100))    # fix_replace_alternator
_kb.add_rule(Rule("PWR-005 低温导致电瓶容量下降", [_has("car_wont_start"), _has("slow_crank"), _has("cold_weather")], Fact("cold_cranking_weak"), 50))            # fix_warm_battery_or_jump_start

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("BAT-101 中间事实：起动功率不足", [_has("car_wont_start"), _has("slow_crank"), _has("battery_voltage_low")], Fact("cranking_power_insufficient"), 60))     # 下游：电瓶侧 / 充电侧

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("BAT-102 中间事实：故障集中在电瓶侧", [_has("car_wont_start"), _has("cranking_power_insufficient"), _has("jump_start_ok")], Fact("battery_side_fault"), 60))  # 下游：寿命 / 充电

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("BAT-201 电瓶已到寿命（链式）", [_has("car_wont_start"), _has("battery_side_fault"), _has("battery_old")], Fact("battery_end_of_life"), 100))               # fix_replace_battery
_kb.add_rule(Rule("BAT-202 充电系统异常导致反复亏电（链式）", [_has("car_wont_start"), _has("battery_side_fault"), _has("alternator_fault")], Fact("charging_fault_confirmed"), 100))  # fix_check_charging_voltage

# 链式：起动机侧
_kb.add_rule(Rule("START-101 中间事实：供电正常但起动机不动作", [_has("car_wont_start"), _has("no_crank"), _has("headlights_bright")], Fact("starter_no_action"), 60))        # 下游：电磁开关 / 电机本体
_kb.add_rule(Rule("START-201 起动机电磁开关只吸不转（链式）", [_has("car_wont_start"), _has("starter_no_action"), _has("click_sound_only")], Fact("starter_solenoid_fault"), 100))  # fix_replace_starter_solenoid
_kb.add_rule(Rule("START-202 起动机碳刷/转子故障（链式）", [_has("car_wont_start"), _has("starter_no_action"), _has("starter_motor_fault")], Fact("starter_motor_confirmed"), 50))     # fix_overhaul_starter_motor

# ===================== 供油系统 =====================
_kb.add_rule(Rule("FUEL-001 燃油耗尽", [_has("car_wont_start"), _has("fuel_gauge_empty")], Fact("out_of_fuel"), 100))                                                # fix_refuel
_kb.add_rule(Rule("FUEL-002 燃油泵不工作", [_has("car_wont_start"), _has("cranks_no_start"), _has("fuel_pump_noise_missing")], Fact("fuel_pump_fault"), 100))         # fix_replace_fuel_pump
_kb.add_rule(Rule("FUEL-003 喷油嘴堵塞", [_has("car_wont_start"), _has("start_then_stall"), _has("fuel_injector_clogged")], Fact("injector_clogged"), 50))            # fix_clean_or_replace_injector

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("FUEL-101 中间事实：供油压力不足", [_has("car_wont_start"), _has("cranks_no_start"), _has("fuel_pressure_low")], Fact("fuel_supply_insufficient"), 60))       # 下游：滤清器 / 油泵继电器

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("FUEL-201 燃油滤清器堵塞（链式）", [_has("car_wont_start"), _has("fuel_supply_insufficient"), _has("fuel_filter_clogged")], Fact("fuel_filter_blocked"), 100))  # fix_replace_fuel_filter
_kb.add_rule(Rule("FUEL-202 油泵继电器故障（链式）", [_has("car_wont_start"), _has("fuel_supply_insufficient"), _has("pump_relay_silent")], Fact("pump_relay_fault"), 100))       # fix_replace_fuel_pump_relay

# ===================== 点火系统 =====================
_kb.add_rule(Rule("IGN-001 火花塞积碳或油污", [_has("car_wont_start"), _has("cranks_no_start"), _has("spark_plug_fouled")], Fact("spark_plug_fault"), 100))             # fix_replace_spark_plug
_kb.add_rule(Rule("IGN-002 点火线圈失效", [_has("car_wont_start"), _has("cranks_no_start"), _has("no_spark")], Fact("ignition_coil_fault"), 100))                     # fix_replace_ignition_coil
_kb.add_rule(Rule("IGN-003 曲轴位置传感器故障", [_has("car_wont_start"), _has("cranks_no_start"), _has("no_spark"), _has("crankshaft_sensor_fault")], Fact("crankshaft_sensor_failure"), 100))  # fix_replace_crank_sensor

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("IGN-101 中间事实：点火能量不足", [_has("car_wont_start"), _has("cranks_no_start"), _has("spark_weak")], Fact("ignition_energy_weak"), 60))            # 下游：燃烧稳定性

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("IGN-102 中间事实：燃烧不稳定", [_has("car_wont_start"), _has("ignition_energy_weak"), _has("start_then_stall")], Fact("unstable_combustion"), 60))         # 下游：点火系统老化 / 线圈热衰退

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("IGN-201 点火系统老化（链式）", [_has("car_wont_start"), _has("unstable_combustion"), _has("spark_plug_fouled")], Fact("ignition_system_worn"), 100))       # fix_full_ignition_service
_kb.add_rule(Rule("IGN-202 点火线圈热衰退（链式）", [_has("car_wont_start"), _has("unstable_combustion"), _has("ignition_coil_overheat")], Fact("coil_heat_failure"), 50))     # fix_replace_coil_when_hot

# ===================== 进气与配气 =====================
_kb.add_rule(Rule("AIR-001 空气滤芯严重堵塞", [_has("car_wont_start"), _has("start_then_stall"), _has("air_filter_clogged")], Fact("air_intake_blocked"), 50))          # fix_replace_air_filter
_kb.add_rule(Rule("AIR-002 空气流量计故障", [_has("car_wont_start"), _has("start_then_stall"), _has("maf_sensor_fault")], Fact("maf_fault"), 100))                     # fix_clean_or_replace_maf
_kb.add_rule(Rule("AIR-003 节气门积碳卡滞", [_has("car_wont_start"), _has("start_then_stall"), _has("throttle_body_dirty")], Fact("throttle_sticking"), 50))            # fix_clean_throttle_body
_kb.add_rule(Rule("AIR-004 正时皮带/链条错位", [_has("car_wont_start"), _has("cranks_no_start"), _has("timing_belt_jumped")], Fact("timing_misaligned"), 100))          # fix_realign_timing
_kb.add_rule(Rule("AIR-005 缸压不足（活塞环/气门）", [_has("car_wont_start"), _has("cranks_no_start"), _has("compression_low")], Fact("low_compression"), 100))         # fix_engine_mechanical_check

# ===================== 防盗与电控 =====================
_kb.add_rule(Rule("IMMO-001 防盗系统未解除", [_has("car_wont_start"), _has("cranks_no_start"), _has("immobilizer_light_on")], Fact("immobilizer_active"), 100))          # fix_use_spare_key_or_reset_immo
_kb.add_rule(Rule("IMMO-002 钥匙芯片不被识别", [_has("car_wont_start"), _has("cranks_no_start"), _has("key_not_recognized")], Fact("key_not_recognized_fault"), 100))     # fix_replace_key_battery_or_reprogram
