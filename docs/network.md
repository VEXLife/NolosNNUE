# NOLOS001 网络格式

Rust 推理实现位于 `src/network.rs`，PyTorch 实现位于 `trainer/model.py`。不同架构、非有限参数、校验错误和长度不匹配都会被拒绝，旧网络保持有效。

## 特征

棋盘被分解成水平、垂直和两条对角线。长度少于五的整条线忽略。对长度为 L 的线，六格窗口起点遍历 -5 到 L-1；越界位置编码为 3，空=0、黑=1、白=2。窗口最低两位对应第一个位置。

每个窗口与反向编码取较小值，累计为 `counts[4096]`。白方视角把编码中的 1、2 交换后再次规范化。方向共享嵌入，特征对棋盘的八种旋转／镜像不变。

```text
black_acc = bias + sum(count[id] × embedding[id]) / 32
white_acc = bias + sum(count[id] × embedding[invert(id)]) / 32
black_logit = sum((clip(black_acc,0,1) - clip(white_acc,0,1)) × head)
side_logit = (black_to_play ? black_logit : -black_logit) + tempo
evaluation = round(side_logit × 600), clamped to [-12000,12000]
```

每次落子只修改包含该格的窗口、计数、累加器与 HCE 棋形分数。撤子反向更新。新搜索和权重加载时完整重建累加器，控制浮点累计误差。测试允许各后端评估相差不超过 1 个分值。

NOLOS001 增量累加器在 x86_64 上运行时检测 AVX，以 256 位向量并行更新 8 个 f32 通道；其他 CPU 和 WASM 使用标量路径。实现位于 `src/simd.rs`，无需全局启用 AVX 编译选项，不使用 FMA 或改变求和顺序。此优化不影响 HCE 或 NOLOS002。

2026-10-05 本机 Ryzen 5 4600H 使用 `artifacts/gen9.nnue` 对照：三个 10 万节点局面、七轮交替测试，中位耗时合计下降 6.64%（吞吐提升 7.11%），搜索诊断结果全部一致；另一个仅两节点的杀棋局面不计入汇总。此为小样本本机结果；局面、二进制基线、SHA 和原始记录位于 `.agent/simd-20261005/`，最终报告为 `avx-clean.json`。

可选 `INFO nnue_precision int16` 在加载时从原始 NOLOS001 权重生成 i16 嵌入表，以 i32 累加器更新；x86_64 自动检测 AVX2，其他平台使用整数标量路径。缩放单位为不超过 262144 的二次幂，按最大嵌入权重选择，使量化后的权重不溢出；偏置采用同一累加器单位，head 和 tempo 保持 f32。支持的 5..20 棋盘累加值不会溢出 i32，撤子可精确恢复整数累加器。热点嵌入表为浮点表的一半大小；为支持恢复 fp32，内存仍保留原始浮点权重，模型文件不变。

默认 `fp32`；用 `INFO nnue_precision fp32` 恢复。切换只能在空闲、非 BOARD 输入期间进行，会重建累加器并清空置换表。加载 NOLOS002 前须恢复 fp32；HCE 不使用量化。量化可能改变评估和搜索树，速度及误差须针对实际模型复测。诊断入口为 `src/bin/inference_bench.rs`、`src/bin/search_bench.rs` 的 `--precision` / `--time-ms` 参数，以及交替对照脚本 `scripts/compare_precision_bench.py`。

原生启动可传 `--weights PATH --precision int16`，不传精度参数时仍为 fp32。2026-10-05 本机 Ryzen 5 4600H、`artifacts/gen9.nnue`、十个局面七轮交替对照：五个跑满 10 万节点的局面中位耗时合计下降 2.92%，每步 1 秒时节点数增加 2.43%，完成深度仍相同；十个局面的最佳着均一致。2000 个确定性随机局面平均绝对评估误差 0.2295 分、95 分位和最大值均为 1 分。相同落子／评估／撤子工作量耗时下降 15.32%；此微基准不代表整个搜索收益。默认 fp32 与修改前五轮对照的耗时变化为 +0.18%，未见明显回退。保留默认关闭的实验选项，尚未证明棋力提升或稳定增加完成深度。原始样本、命令、二进制和 SHA 位于 `.agent/quant-20261005/`，最终对照为 `results-avx2.json`。

同日 INT8 隔离实验采用每通道对称缩放、i8 嵌入、i32 累加器和 AVX2，head／tempo 保持 f32。各 2000 个随机局面：gen9 平均绝对误差 34.505 分、最大 222 分；`runs/hce-local-002` 的 generation-001 冠军平均 18.2865 分、最大 118 分。两模型、五个局面、三轮交替的 5 万节点／1 秒对照未稳定增加完成深度；002 的一个局面完成深度由 7 降为 6，另一局面的限时选着有变化。同量计算未显示 INT8 稳定优于 INT16；固定节点耗时也受量化导致的搜索树变化影响。未并入正式引擎或续训配置。原型、模型快照、CPU／墙钟样本和 SHA 位于 `.agent/int8-20261005/`，报告为 `hce002.json`、`gen9.json`。

## 二进制布局

全部整数／浮点使用 little-endian，f32 为 IEEE-754。文件总长度 **524576 字节**。

| 偏移 | 长度 | 含义 |
| --- | --- | --- |
| 0 | 8 | ASCII `NOLOS001` |
| 8 | 4 | u32 特征数量 4096 |
| 12 | 4 | u32 隐藏维度 32 |
| 16 | 4 | f32 特征归一化 32.0 |
| 20 | 4 | f32 分值倍率 600.0 |
| 24 | 4 | u32 payload 的 FNV-1a 校验 |
| 28 | 524288 | f32 embedding[4096][32]，按特征排列 |
| 524316 | 128 | f32 bias[32] |
| 524444 | 128 | f32 head[32] |
| 524572 | 4 | f32 tempo |

FNV-1a 初值 2166136261，每字节 `(hash XOR byte) × 16777619`，取低 32 位。SHA-256 另外记录于训练日志，用于标识完整文件；FNV 校验不是安全签名。

`.pt` 是 PyTorch state_dict，用 `weights_only=True` 读取；它用于继续训练和一致性验证，浏览器／Rust 不读取 `.pt`。

## 标签与评测

训练输出为当前行棋方胜率的 logit。默认目标为 `0.7 × sigmoid(search_score/600) + 0.3 × game_outcome`；截断局面仅使用搜索标签。旧版训练数据曾过滤近必胜分值；新生成的数据保留搜索证明局面，但不采样已经结束的棋盘。验证按整盘游戏分组，最佳验证损失选择导出检查点。最终晋升仍由独立开局对战决定。

# NOLOS002 局部价值／策略网络

新结构与 NOLOS001 同时受支持。每个交点读取四个长度为 9、以该点为中心的方向窗口，边界仍编码为 3；对反转取较小编码，得到 262144 种索引。黑白两套视角共享参数：

```text
local[p] = ReLU(local_bias + 0.5 × sum(embedding[direction_id[p,d]]))
features[p] = concat(local_own[p], local_opponent[p])
pooled = mean(features[p] over all board intersections)
value = ReLU(value_in × pooled + value_bias) · value_out + value_out_bias
policy[p] = features[p] · policy + policy_bias
```

局部宽度 16，价值隐藏宽度 32。当前行棋方决定 own/opponent 顺序；价值乘 600、四舍五入并截到 ±12000。策略输出为原始 logit；训练时屏蔽已有棋子的位置。池化分母为棋盘交点总数。

28 字节头部保持相同布局，magic 改为 `NOLOS002`，特征数 262144，隐藏宽度 16，归一化字段 1.0，分值倍率 600.0。payload 按以下顺序存储 little-endian f32：

1. embedding[262144][16]
2. local_bias[16]
3. policy[32]、policy_bias
4. value_in[32][32]，行优先
5. value_bias[32]、value_out[32]、value_out_bias

共 4195442 个参数，总文件长度 16781796 字节，仍使用 payload FNV-1a 校验。训练与 Rust 推理的结构必须完全匹配。

新自对弈数据包括 `best_move`（0 起始的行优先交点）和 `vcf_depth`。搜索证明的局面可具有 `depth=0`、`vcf_depth>0`，现在保留为训练数据。旧 JSONL 没有策略标签时仅参与价值损失。spatial训练默认损失为每个局面的价值 BCE 加 0.5 倍策略交叉熵；无策略标签的局面不贡献策略损失。验证仍按整盘分组，导出联合验证损失最低的检查点，晋升另由对局决定。
