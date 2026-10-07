# ./example/ml_training.py
"""
# 机器学习训练异常诊断知识库 · ml_training_issues

## 用途
把「训练日志里看到的现象」翻译成「最可能的原因」。知识库按环节划分：
数据 → 优化与超参 → 模型结构 → 工程与性能，并给出跨环节的链式推理。

面向 PyTorch / TensorFlow 这类深度学习训练，规则里的现象名尽量贴近日志与监控指标
（loss、准确率、梯度范数、显存占用）。

## 推理方式
每条规则的条件都是 `has_<事实名>`：只要工作记忆里存在同名事实，条件就成立
（事实的 `value` 不参与匹配）。规则分三类：

- **根因规则**（优先级 100）：结论直接是原因，例如 `overfitting_confirmed`、
  `fp16_overflow_issue`。
- **链式中间事实**（优先级 60）：结论是中间结论，例如 `optimization_unstable`、
  `generalization_gap`，会被下游规则继续消费。
- **低置信分支**（优先级 50）：需要更多证据，通常作为排查方向。

所有规则都要求 `training_started` 成立 —— 表示「训练脚本已经跑起来了」。

## 使用步骤
1. 在「知识库」面板选中本示例并点「载入」；
2. 用下面的模板（或自写的事实名）断言观察到的现象；
3. 点「单步」逐条观察规则触发，或点「单步到底 / 运行到底」跑到不动点；
4. 在「推理轨迹」里核对 IF（条件）/ THEN（结论），确认原因。

## 断言语法
一行一条事实，等号后面可以跟值：

```text
training_started            # 省略值 → true
batch_size = 8              # 数字
```

## 示例事实模板
点代码块右上角的「一键填入」会**先清空工作记忆**，再把这些事实写进去 ——
相当于一键切换到该故障场景。如果想保留已有事实，请用「批量断言」表单。

### 1. loss 剧烈震荡（学习率过大 + 无梯度裁剪）

```facts
training_started
loss_oscillating
lr_too_large
gradient_norm_huge
no_grad_clip
```

OPT-101 → OPT-102，再由 OPT-202 得到 `grad_clip_missing`；
OPT-001 给出 `lr_excessive`。先把学习率除以 5～10，再补上梯度裁剪。

### 2. loss 变成 NaN（梯度爆炸 + fp16 溢出）

```facts
training_started
loss_nan
gradient_norm_huge
mixed_precision_enabled
fp16_overflow
```

OPT-003 给出 `exploding_gradients`，ENG-002 给出 `fp16_overflow_issue`。
两者经常同时出现：fp16 的动态范围太窄，梯度一大就溢出成 inf/nan。

### 3. 训练集 loss 降、验证集 loss 升（过拟合）

```facts
training_started
train_loss_down_val_loss_up
overfit_gap_large
no_regularization
train_set_too_small
```

MODEL-101 → MODEL-102 → MODEL-201，得到 `overfitting_confirmed`；
MODEL-001 给出 `overfitting`，MODEL-003 给出 `regularization_missing`，
DATA-003 给出 `insufficient_data`。

### 4. 准确率停在随机水平（标签错位 / 指标算错）

```facts
training_started
accuracy_stuck_at_random
label_mismatch
metric_wrong
class_imbalance
```

DATA-101 先得出中间事实 `unreliable_training_signal`，
再由 DATA-201 得到 `label_error_confirmed`，DATA-202 得到 `imbalance_metric_distortion`。
先固定随机种子，用几十条样本过拟合一遍，能过拟合说明是数据/指标问题而不是模型问题。

### 5. 梯度范数接近 0（梯度消失 / ReLU 死亡）

```facts
training_started
gradient_norm_zero
vanishing_gradient
dead_relu
weight_init_bad
```

OPT-004 给出 `vanishing_gradients`，MODEL-005 给出 `dead_relu_issue`，
MODEL-006 给出 `bad_initialization`。可以换成 GELU 或把初始化改成
Kaiming/He 再试。

### 6. 收敛极慢（学习率过小 / 没有调度）

```facts
training_started
loss_decreasing_very_slow
lr_too_small
no_lr_scheduler
```

OPT-002 给出 `lr_insufficient`，OPT-007 给出 `no_scheduler`。
先跑一个 lr range test 找合适的学习率区间。

### 7. 显存溢出 + GPU 利用率低

```facts
training_started
gpu_oom
dataloader_bottleneck
num_workers_zero
```

ENG-001 给出 `oom_error`，ENG-003 给出 `dataloader_slow`。
显存不够先降 batch 或上梯度累积；`num_workers=0` 会让数据加载卡住 GPU。
"""
import copy

from core.model import Fact, KnowledgeBase, Rule

__name__ = "ml_training_issues"

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

# ===================== 数据 =====================
_kb.add_rule(Rule("DATA-001 输入未做归一化", [_has("training_started"), _has("unnormalized_input"), _has("loss_oscillating")], Fact("input_scale_issue"), 100))            # fix_normalize_inputs
_kb.add_rule(Rule("DATA-002 训练集与验证集重叠", [_has("training_started"), _has("data_leakage"), _has("val_metric_suspiciously_good")], Fact("validation_leakage"), 100))       # fix_rebuild_split
_kb.add_rule(Rule("DATA-003 训练样本太少", [_has("training_started"), _has("train_set_too_small"), _has("overfit_gap_large")], Fact("insufficient_data"), 100))                # fix_collect_more_data_or_augment

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("DATA-101 中间事实：训练信号不可信", [_has("training_started"), _has("label_mismatch"), _has("accuracy_stuck_at_random")], Fact("unreliable_training_signal"), 60))  # 下游：标签 / 指标

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("DATA-201 标签错位（链式）", [_has("training_started"), _has("unreliable_training_signal"), _has("metric_wrong")], Fact("label_error_confirmed"), 100))           # fix_verify_label_pipeline
_kb.add_rule(Rule("DATA-202 类别不平衡导致指标失真（链式）", [_has("training_started"), _has("unreliable_training_signal"), _has("class_imbalance")], Fact("imbalance_metric_distortion"), 100))  # fix_use_f1_or_auc

# ===================== 优化与超参 =====================
_kb.add_rule(Rule("OPT-001 学习率过大", [_has("training_started"), _has("loss_oscillating"), _has("lr_too_large")], Fact("lr_excessive"), 100))                        # fix_lower_learning_rate
_kb.add_rule(Rule("OPT-002 学习率过小", [_has("training_started"), _has("loss_decreasing_very_slow"), _has("lr_too_small")], Fact("lr_insufficient"), 100))              # fix_raise_learning_rate
_kb.add_rule(Rule("OPT-003 梯度爆炸", [_has("training_started"), _has("gradient_norm_huge"), _has("loss_nan")], Fact("exploding_gradients"), 100))                     # fix_clip_gradients
_kb.add_rule(Rule("OPT-004 梯度消失", [_has("training_started"), _has("gradient_norm_zero"), _has("vanishing_gradient")], Fact("vanishing_gradients"), 100))             # fix_use_residual_or_norm
_kb.add_rule(Rule("OPT-005 忘记梯度清零", [_has("training_started"), _has("not_zero_grad"), _has("loss_oscillating")], Fact("missing_zero_grad"), 100))                 # fix_call_optimizer_zero_grad
_kb.add_rule(Rule("OPT-006 损失函数与任务不匹配", [_has("training_started"), _has("wrong_loss_function"), _has("both_losses_high")], Fact("loss_function_mismatch"), 100))  # fix_match_loss_to_task
_kb.add_rule(Rule("OPT-007 缺少学习率调度", [_has("training_started"), _has("no_lr_scheduler"), _has("loss_decreasing_very_slow")], Fact("no_scheduler"), 50))            # fix_add_cosine_schedule
_kb.add_rule(Rule("OPT-008 缺少 warmup", [_has("training_started"), _has("lr_warmup_missing"), _has("loss_nan")], Fact("no_warmup"), 50))                              # fix_add_warmup_steps

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("OPT-101 中间事实：优化过程不稳定", [_has("training_started"), _has("loss_oscillating"), _has("lr_too_large")], Fact("optimization_unstable"), 60))       # 下游：梯度尺度

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("OPT-102 中间事实：梯度尺度失控", [_has("training_started"), _has("optimization_unstable"), _has("gradient_norm_huge")], Fact("gradient_scale_uncontrolled"), 60))  # 下游：batch / 裁剪

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("OPT-201 学习率与 batch 不匹配（链式）", [_has("training_started"), _has("gradient_scale_uncontrolled"), _has("batch_size_too_small")], Fact("lr_batch_mismatch"), 100))  # fix_scale_lr_with_batch
_kb.add_rule(Rule("OPT-202 缺少梯度裁剪（链式）", [_has("training_started"), _has("gradient_scale_uncontrolled"), _has("no_grad_clip")], Fact("grad_clip_missing"), 100))                 # fix_clip_grad_norm

# ===================== 模型结构 =====================
_kb.add_rule(Rule("MODEL-001 过拟合", [_has("training_started"), _has("train_loss_down_val_loss_up"), _has("overfit_gap_large")], Fact("overfitting"), 100))               # fix_add_regularization
_kb.add_rule(Rule("MODEL-002 欠拟合", [_has("training_started"), _has("both_losses_high"), _has("model_too_small")], Fact("underfitting"), 100))                         # fix_increase_capacity
_kb.add_rule(Rule("MODEL-003 缺少正则化", [_has("training_started"), _has("overfitting"), _has("no_regularization")], Fact("regularization_missing"), 100))               # fix_add_weight_decay
_kb.add_rule(Rule("MODEL-004 缺少 Dropout", [_has("training_started"), _has("overfitting"), _has("no_dropout")], Fact("dropout_missing"), 50))                           # fix_add_dropout
_kb.add_rule(Rule("MODEL-005 ReLU 神经元死亡", [_has("training_started"), _has("dead_relu"), _has("gradient_norm_zero")], Fact("dead_relu_issue"), 100))                 # fix_switch_to_gelu_or_leaky
_kb.add_rule(Rule("MODEL-006 权重初始化不当", [_has("training_started"), _has("weight_init_bad"), _has("gradient_norm_zero")], Fact("bad_initialization"), 50))            # fix_use_kaiming_init
_kb.add_rule(Rule("MODEL-007 BatchNorm 批太小", [_has("training_started"), _has("bn_batch_too_small"), _has("loss_oscillating")], Fact("bn_instability"), 50))           # fix_use_group_norm

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("MODEL-101 中间事实：泛化差距大", [_has("training_started"), _has("train_loss_down_val_loss_up")], Fact("generalization_gap"), 60))                     # 下游：记忆训练集

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("MODEL-102 中间事实：模型在记忆训练集", [_has("training_started"), _has("generalization_gap"), _has("train_set_too_small")], Fact("model_memorizing"), 60))   # 下游：过拟合 / 不平衡

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("MODEL-201 过拟合确诊（链式）", [_has("training_started"), _has("model_memorizing"), _has("no_regularization")], Fact("overfitting_confirmed"), 100))        # fix_regularize_and_augment
_kb.add_rule(Rule("MODEL-202 不平衡数据放大过拟合（链式）", [_has("training_started"), _has("generalization_gap"), _has("class_imbalance")], Fact("imbalance_overfit"), 50))     # fix_resample_or_reweight

# ===================== 工程与性能 =====================
_kb.add_rule(Rule("ENG-001 显存不足", [_has("training_started"), _has("gpu_oom")], Fact("oom_error"), 100))                                                          # fix_reduce_batch_or_use_amp
_kb.add_rule(Rule("ENG-002 混合精度 fp16 溢出", [_has("training_started"), _has("mixed_precision_enabled"), _has("fp16_overflow"), _has("loss_nan")], Fact("fp16_overflow_issue"), 100))  # fix_enable_loss_scaling
_kb.add_rule(Rule("ENG-003 数据加载成为瓶颈", [_has("training_started"), _has("dataloader_bottleneck"), _has("num_workers_zero")], Fact("dataloader_slow"), 100))           # fix_increase_num_workers
_kb.add_rule(Rule("ENG-004 验证时忘记 eval 模式", [_has("training_started"), _has("eval_mode_missing"), _has("val_loss_high")], Fact("eval_mode_issue"), 100))             # fix_call_model_eval
_kb.add_rule(Rule("ENG-005 随机种子未固定", [_has("training_started"), _has("seed_not_fixed"), _has("loss_oscillating")], Fact("non_reproducible"), 50))                 # fix_set_random_seed
_kb.add_rule(Rule("ENG-006 评估指标实现有误", [_has("training_started"), _has("metric_wrong"), _has("accuracy_stuck_at_random")], Fact("metric_implementation_bug"), 100))  # fix_unit_test_metric
