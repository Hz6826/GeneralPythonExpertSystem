# ./example/crop.py
"""
# 番茄病害与长势异常诊断知识库 · crop_disease

## 用途
把「田间/阳台观察到的叶片、茎、果实异常」翻译成「最可能的营养、病害、虫害或栽培问题」。
知识库按成因划分：营养失调 → 侵染性病害 → 虫害 → 环境与栽培，并给出跨类别的链式推理。

以番茄为示例作物，规则中的症状描述对其他茄果类（辣椒、茄子）也大体通用。

## 推理方式
每条规则的条件都是 `has_<事实名>`：只要工作记忆里存在同名事实，条件就成立
（事实的 `value` 不参与匹配）。规则分三类：

- **根因规则**（优先级 100）：结论直接是成因，例如 `early_blight_outbreak`、
  `waterlogging_nutrient_lockout`。
- **链式中间事实**（优先级 60）：结论是中间结论，例如 `root_zone_anoxia`、
  `disease_spreading`，会被下游规则继续消费。
- **低置信分支**（优先级 50）：需要更多证据，通常作为排查方向。

所有规则都要求 `tomato_planted` 成立 —— 表示「已经种下番茄并处于生长期」。

## 使用步骤
1. 在「知识库」面板选中本示例并点「载入」；
2. 用下面的模板（或自写的事实名）断言观察到的现象；
3. 点「单步」逐条观察规则触发，或点「单步到底 / 运行到底」跑到不动点；
4. 在「推理轨迹」里核对 IF（条件）/ THEN（结论），确认成因。

## 断言语法
一行一条事实，等号后面可以跟值：

```text
tomato_planted              # 省略值 → true
soil_ph = 7.8               # 数字
```

## 示例事实模板
点代码块右上角的「一键填入」会**先清空工作记忆**，再把这些事实写进去 ——
相当于一键切换到该故障场景。如果想保留已有事实，请用「批量断言」表单。

### 1. 老叶先黄、植株矮小（缺氮）

```facts
tomato_planted
lower_leaves_yellow
stunted_growth
```

NUT-001 给出 `nitrogen_deficiency`。缺氮的典型特征就是**从下往上**黄，
新叶相对正常。

### 2. 新叶脉间失绿、土壤偏碱（缺铁）

```facts
tomato_planted
upper_leaves_yellow
leaf_yellow_between_veins
soil_alkaline
```

NUT-101 先得出中间事实 `young_leaf_chlorosis`，NUT-201 落到
`iron_chlorosis_from_ph`（碱性土导致铁不可吸收）。若同时 `soil_waterlogged`，
NUT-202 会给出 `iron_uptake_blocked`（根系吸收障碍）。

### 3. 叶片褐色斑点、高温高湿（早疫病扩散）

```facts
tomato_planted
leaf_spot_brown
lower_leaves_yellow
hot_humid_weather
dense_planting
```

DIS-101 → DIS-102 → DIS-201，得到 `early_blight_outbreak`；
DIS-001 同时给出 `early_blight`，ENV-006 给出 `poor_ventilation`（种植过密通风差）。

### 4. 中午萎蔫、土壤积水（沤根导致缺素）

```facts
tomato_planted
soil_waterlogged
root_brown_rot
upper_leaves_yellow
wilt_at_noon
```

ENV-101 → ENV-102 → ENV-201，得到 `waterlogging_nutrient_lockout`：
根区缺氧 → 吸收受阻 → 表现出缺素，但真正的问题是浇水过多。
ENV-002 给出 `waterlogging_stress`；若同时 `permanent_wilt`，ENV-202 会给出
`root_rot_confirmed`。

### 5. 果实脐部黑腐（缺钙）

```facts
tomato_planted
fruit_blossom_end_rot
```

NUT-003 给出 `calcium_deficiency`。脐腐病不是病菌引起，而是钙的运输跟不上，
多与水分忽干忽湿有关。

### 6. 蚜虫/白粉虱伴随花叶（病毒病）

```facts
tomato_planted
aphids_present
whiteflies_present
mosaic_leaf_pattern
leaf_curl_down
```

PEST-001 → PEST-101，再经 PEST-201 得到 `viral_disease`（病毒病经刺吸式害虫传播）。
病毒病无法治愈，重点在控虫与拔除病株。
"""
import copy

from core.model import Fact, KnowledgeBase, Rule

__name__ = "crop_disease"

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

# ===================== 营养失调 =====================
_kb.add_rule(Rule("NUT-001 缺氮（老叶先黄）", [_has("tomato_planted"), _has("lower_leaves_yellow"), _has("stunted_growth")], Fact("nitrogen_deficiency"), 100))        # fix_apply_nitrogen_fertilizer
_kb.add_rule(Rule("NUT-002 缺钾（叶缘焦枯+果小）", [_has("tomato_planted"), _has("leaf_margin_burn"), _has("fruit_small")], Fact("potassium_deficiency"), 100))          # fix_apply_potassium_fertilizer
_kb.add_rule(Rule("NUT-003 缺钙（果实脐腐）", [_has("tomato_planted"), _has("fruit_blossom_end_rot")], Fact("calcium_deficiency"), 100))                              # fix_calcium_spray_and_steady_water
_kb.add_rule(Rule("NUT-004 施肥过量烧根", [_has("tomato_planted"), _has("leaf_margin_burn"), _has("fertilizer_burn_sign")], Fact("fertilizer_burn"), 50))            # fix_flush_substrate

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("NUT-101 中间事实：新叶脉间失绿", [_has("tomato_planted"), _has("upper_leaves_yellow"), _has("leaf_yellow_between_veins")], Fact("young_leaf_chlorosis"), 60))  # 下游：缺铁

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("NUT-201 碱性土导致缺铁（链式）", [_has("tomato_planted"), _has("young_leaf_chlorosis"), _has("soil_alkaline")], Fact("iron_chlorosis_from_ph"), 100))        # fix_lower_soil_ph
_kb.add_rule(Rule("NUT-202 根系吸收障碍导致缺铁（链式）", [_has("tomato_planted"), _has("young_leaf_chlorosis"), _has("soil_waterlogged")], Fact("iron_uptake_blocked"), 50))   # fix_improve_drainage

# ===================== 侵染性病害 =====================
_kb.add_rule(Rule("DIS-001 早疫病", [_has("tomato_planted"), _has("leaf_spot_brown"), _has("lower_leaves_yellow")], Fact("early_blight"), 100))                       # fix_remove_infected_leaves_and_spray
_kb.add_rule(Rule("DIS-002 细菌性斑点病", [_has("tomato_planted"), _has("leaf_spot_with_halo")], Fact("bacterial_spot"), 100))                                      # fix_apply_copper_bactericide
_kb.add_rule(Rule("DIS-003 灰霉病", [_has("tomato_planted"), _has("leaf_mold_fuzzy"), _has("hot_humid_weather")], Fact("gray_mold"), 100))                           # fix_ventilate_and_remove_flowers
_kb.add_rule(Rule("DIS-004 白粉病", [_has("tomato_planted"), _has("leaf_white_powder")], Fact("powdery_mildew"), 100))                                              # fix_apply_sulfur_or_bicarbonate
_kb.add_rule(Rule("DIS-005 枯萎病（茎中空）", [_has("tomato_planted"), _has("permanent_wilt"), _has("stem_hollow")], Fact("fusarium_wilt"), 100))                     # fix_uproot_and_rotate_crop
_kb.add_rule(Rule("DIS-006 茎基腐病", [_has("tomato_planted"), _has("stem_lesion_dark"), _has("permanent_wilt")], Fact("stem_rot"), 50))                            # fix_improve_soil_aeration

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("DIS-101 中间事实：叶部真菌感染", [_has("tomato_planted"), _has("leaf_spot_brown"), _has("hot_humid_weather")], Fact("fungal_leaf_infection"), 60))     # 下游：扩散条件

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("DIS-102 中间事实：病害正在扩散", [_has("tomato_planted"), _has("fungal_leaf_infection"), _has("dense_planting")], Fact("disease_spreading"), 60))      # 下游：早疫病 / 灰霉病

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("DIS-201 早疫病扩散（链式）", [_has("tomato_planted"), _has("disease_spreading"), _has("lower_leaves_yellow")], Fact("early_blight_outbreak"), 100))         # fix_spray_and_prune_lower_leaves
_kb.add_rule(Rule("DIS-202 灰霉病爆发（链式）", [_has("tomato_planted"), _has("disease_spreading"), _has("leaf_mold_fuzzy")], Fact("gray_mold_outbreak"), 100))                # fix_lower_humidity_and_spray

# ===================== 虫害 =====================
_kb.add_rule(Rule("PEST-001 蚜虫危害", [_has("tomato_planted"), _has("aphids_present"), _has("leaf_curl_down")], Fact("aphid_damage"), 100))                          # fix_spray_soap_or_imidacloprid
_kb.add_rule(Rule("PEST-002 白粉虱危害", [_has("tomato_planted"), _has("whiteflies_present"), _has("leaf_curl_up")], Fact("whitefly_damage"), 100))                   # fix_yellow_sticky_trap_and_spray
_kb.add_rule(Rule("PEST-003 红蜘蛛危害", [_has("tomato_planted"), _has("spider_mites_webs"), _has("leaf_yellow_between_veins")], Fact("spider_mite_damage"), 100))       # fix_increase_humidity_and_miticide

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("PEST-101 中间事实：刺吸式害虫压力大", [_has("tomato_planted"), _has("aphids_present"), _has("whiteflies_present")], Fact("sucking_pest_pressure"), 60))    # 下游：病毒病 / 煤污病

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("PEST-201 病毒病经媒介传播（链式）", [_has("tomato_planted"), _has("sucking_pest_pressure"), _has("mosaic_leaf_pattern")], Fact("viral_disease"), 100))       # fix_control_vector_and_remove_plant
_kb.add_rule(Rule("PEST-202 伴随煤污病（链式）", [_has("tomato_planted"), _has("sucking_pest_pressure"), _has("leaf_sooty_mold")], Fact("sooty_mold"), 50))                    # fix_wash_leaves_and_control_pests

# ===================== 环境与栽培 =====================
_kb.add_rule(Rule("ENV-001 光照不足", [_has("tomato_planted"), _has("poor_light"), _has("stunted_growth")], Fact("insufficient_light"), 100))                        # fix_move_to_sunnier_spot
_kb.add_rule(Rule("ENV-002 土壤积水沤根", [_has("tomato_planted"), _has("soil_waterlogged"), _has("wilt_at_noon")], Fact("waterlogging_stress"), 100))               # fix_improve_drainage
_kb.add_rule(Rule("ENV-003 缺水干旱", [_has("tomato_planted"), _has("soil_dry"), _has("wilt_at_noon")], Fact("drought_stress"), 100))                               # fix_water_regularly
_kb.add_rule(Rule("ENV-004 温度胁迫导致坐果差", [_has("tomato_planted"), _has("cold_night"), _has("fruit_set_poor")], Fact("temperature_stress"), 100))               # fix_stabilize_temperature
_kb.add_rule(Rule("ENV-005 授粉不良", [_has("tomato_planted"), _has("no_pollination"), _has("fruit_set_poor")], Fact("poor_pollination"), 100))                       # fix_hand_pollinate
_kb.add_rule(Rule("ENV-006 种植过密通风差", [_has("tomato_planted"), _has("dense_planting"), _has("hot_humid_weather")], Fact("poor_ventilation"), 50))               # fix_thin_out_plants
_kb.add_rule(Rule("ENV-007 移栽缓苗", [_has("tomato_planted"), _has("transplant_shock"), _has("slow_growth")], Fact("transplant_shock_issue"), 50))                    # fix_shade_and_wait
_kb.add_rule(Rule("ENV-008 水分忽干忽湿导致裂果", [_has("tomato_planted"), _has("fruit_cracking")], Fact("irregular_watering"), 50))                                 # fix_steady_watering

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("ENV-101 中间事实：根区缺氧", [_has("tomato_planted"), _has("soil_waterlogged"), _has("root_brown_rot")], Fact("root_zone_anoxia"), 60))              # 下游：吸收受阻 / 根腐

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("ENV-102 中间事实：根系吸收受阻", [_has("tomato_planted"), _has("root_zone_anoxia"), _has("upper_leaves_yellow")], Fact("nutrient_uptake_blocked"), 60))   # 下游：缺素

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("ENV-201 沤根导致缺素（链式）", [_has("tomato_planted"), _has("nutrient_uptake_blocked"), _has("soil_waterlogged")], Fact("waterlogging_nutrient_lockout"), 100))  # fix_improve_drainage_first
_kb.add_rule(Rule("ENV-202 根腐病（链式）", [_has("tomato_planted"), _has("root_zone_anoxia"), _has("permanent_wilt")], Fact("root_rot_confirmed"), 100))                          # fix_drench_with_fungicide
