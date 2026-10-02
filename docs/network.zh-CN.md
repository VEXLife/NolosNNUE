# NOLOS001 网络格式

[English](network.md) | 简体中文
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

训练输出为当前行棋方胜率的 logit。默认目标为 `0.7 × sigmoid(search_score/600) + 0.3 × game_outcome`；截断局面仅使用搜索标签。训练数据不包含已有终局或搜索发现的近必胜分值。验证按整盘游戏分组，最佳验证损失选择导出检查点。最终晋升仍由独立开局对战决定。
