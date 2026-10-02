# 实验文件

[English](README.md) | 简体中文
- `generation-0.nnue`：最终修正版小样本实验的候选网络，**不是冠军**。512 局 HCE 自对弈生成 8597 个训练位置；256 局评测为 108 胜、146 负、2 和，得分率 42.58%，未晋升。
- `generation-0.training.json`：验证分组、各 epoch 损失与模型 SHA-256。
- `generation-0.arena.json`：独立种子生成的 128 个开局对成绩与近似区间。
- `generation-0.manifest.json`：生成参数、来源校验和与验证记录。

详细命令见 [实验记录](../docs/experiment.zh-CN.md)。原始 JSONL 与 PyTorch `.pt` 保留在本地、已被 `.gitignore` 排除。样例可以用于原生或网页的权重加载测试，但网页默认使用强于此候选的 HCE。
