# HCE自进化训练

当前入口 `scripts/train_hce.sh`，上传包 `artifacts/gomoku-hce-50k-soft.zip`。不包含第9代权重或旧训练数据；初始教师是HCE，学习器随机初始化。既有微调结果见 `docs/history.md`。

默认30代，每代4096盘、每步5万节点、深度上限64、探索率0.6；模型推理保留原始输出，训练数据score在采样过滤后限制为±1000，raw_score保留原始搜索分数；legacy网络最多训练100轮、连续10轮无显著验证改善即早停（min_delta=0.0001）、lr=0.003、纯搜索目标经2.5%标签软化，回放最近4代。总计122880盘，完整运行可能超过云端12小时限时，选择足够长的任务时长或断点续跑。

探索在6～19手以60%概率触发，20～59手线性减小到0，60手停止，可通过EXPLORATION覆盖。遇立即成五或主搜索证明杀棋不探索；不按普通绝对估值关闭探索。候选包含原搜索最佳着、当前教师静态评分最高的另外两着、其余合法候选中均匀随机四着；同分先打乱。每着独立清空置换表，对落子后局面搜索，等分一个正常单步节点预算（七着时每着约7142节点）。未完成搜索或搜索证明必败的候选单独淘汰，不取消其他候选；发现已证明获胜着则优先选择。普通候选按85%温度200分的softmax与15%均匀分布混合抽样，不设100分硬截断；全部被淘汰才回退原最佳着。此策略刻意允许更差但未证明必败的着，扩大教师偏好之外的局面覆盖；有限预算筛选仍可能漏战术，强度收益尚未验证。训练标签仍为原局面的正常搜索结果，额外记录played_move用于审计。钳制仅发生在生成training.jsonl时（--data-score-limit 1000），包括保留下来的杀棋标签；杀棋限采样和普通局面统计先按原始分数完成。selfplay.jsonl保持原样，采样报告记录原始分数范围和钳制数量；训练再做2.5%标签软化，BCE使用原始logit纠正超界预测；搜索杀棋分保持约±30000，HCE评分尺度保持原样。该方案尚未经过云端竞技验证。新配置和源码不能直接续跑旧gen8目录，使用新运行目录。

保留全部普通局面及连续杀棋的前两个局面；排除命中三组保留杀棋及对称变换的整盘。按不可变对局组划分验证集。随机初始化不给高频颜色不变特征引入饱和偏移；后续恢复训练集上不产生贡献的单元。候选即使未晋升也从上一代验证最佳检查点继续学习；教师仅在验证通过后更新。

验证loss最佳模型仅对当前教师进行128对（256盘）等节点对战，得分≥52%、无截断且完成全部对局即晋升。置信区间仅记录；不要求其下界超过50%，不做独立复核、重复挑战HCE或等时间评测。

## 云端启动

服务器已有Python／PyTorch，不需要uv。先更新Cargo环境：

```bash
. "$HOME/.cargo/env" && cd /gemini/code/gomoku-next && THREADS=6 RUN_DIR=/gemini/output/hce-evolution-001 CARGO_TARGET_DIR=/gemini/output/target PYTHONDONTWRITEBYTECODE=1 PYTHON=python bash scripts/train_hce.sh
```

中断后保留同一输出目录、代码与参数，原命令在 `THREADS=6` 前加 `RESUME=1`。已完成阶段校验SHA后复用；未完成阶段重跑。新云任务需将旧输出挂载到相同路径，不能假设不同任务自动共享 `/gemini/output`。

仅更新 Rust 引擎（例如 AVX 加速）后，用原运行配置续跑：`.venv/bin/python -m scripts.resume_engine --run-dir runs/hce-local-002 --accept-engine-update`。入口只接受 `src/*.rs` 的源码差异，拒绝训练器或 shell 脚本变化；旧配置和引擎 SHA 记录在运行目录的 `engine-updates/`，原训练参数、学习器、教师与已完成阶段沿用。`--dry-run` 只核对并显示命令，`--threads N` 仅覆盖自对弈／竞技执行线程。默认推理 FP32 自动使用 AVX，实验量化不进入续训。`hce-local-002` 原配置为 10 线程、CPU 训练、outcome_weight=0.1，不应直接套用当前启动脚本的默认值。

可通过 `GENERATIONS`、`GAMES`、`EPOCHS`、`SELFPLAY_NODES`、`PAIRS`、`TRAIN_DEVICE` 调整配置；续跑须保持相同配置。所有数据、日志、验证最佳学习器／候选、晋升冠军和阶段SHA位于输出目录。没有晋升时不会产生NNUE冠军文件，HCE继续执教。三个用户杀棋不再运行，也不影响晋升。

打包：`python -m scripts.package_hce`。包内 `upload-sha256.json` 可用于核实上传文件。运行需要Rust和带CUDA的PyTorch；GPU训练、CPU自对弈与竞技。

旧包续训：停止旧进程并保留输出，上传新包，将旧输出挂载到 `/gemini/pretrain`。运行 `python -m scripts.resume_hce --run-dir /gemini/output/hce-evolution-001 --accept-first-generation`，自动复制并核验旧产物、迁移评测配置。首代（目录generation-000）依据已完成的59.47%对战结果晋升，跳过剩余复核；后续每代128对、52%阈值。数据和训练结果不重跑，原配置与manifest保留备份。重复续跑使用同一入口即可。
