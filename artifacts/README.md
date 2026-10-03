# 模型与实验产物

Git仅保留当前 `cloud-gen9.nnue`、固定 `search-vcf-fixtures.json` 与本说明。实验日志、诊断、旧模型、`.pt`、数据及上传包默认忽略，仍保留本地。

训练需要 `cloud-gen9.nnue` 与匹配 `.pt`；用 `python -m scripts.package_gen9` 打包两者和最新源码，生成 `gomoku-search-gen9.tgz`。本轮入口见 [训练方案](../docs/training.md)，历史见 [历史摘要](../docs/history.md)。
