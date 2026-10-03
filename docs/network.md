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
