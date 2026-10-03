# 当前训练实验

状态：本轮脚本已实现，尚未提交云端任务。目标是验证新搜索标签能否提升第9代legacy网络，不直接恢复长期多代训练。

## 依据

用户局面 `h8g7i7g9h6j8g8h7j6i6k7k5l8i5k9j5l5k4`：黑走。NNUE静态+571，新搜索84025节点约1.1秒得到−M18；旧搜索80万节点仍+853。关闭NNUE后需283574节点约3秒。因此重训有价值，关闭网络没有依据。

8盘试采样132个局面，115个杀棋、17个普通，提示连续收尾占比过高。小样本不能代表整体分布。数据见 `artifacts/nnue-readiness-{position,selfplay,wasm}.json`。

## 本轮方案

1. 固定当前搜索、更新云端代码；限制连续杀棋收尾，保留首次长杀棋发现，增加普通与攻击前局面。
2. 默认256盘，每步20万节点；按盘轮流选取最多256个节点消耗较高的普通局面，以80万节点重分析。先测CPU耗时及有效样本数，再扩量。
3. 从第9代 `.pt` 微调，legacy架构、lr=3e-5，比较纯搜索与0.3实战混合目标；保存早期checkpoint，固定调度轨迹，保留普通数据。
4. 整盘及同源分支一起划分训练／验证。用户杀棋案例保留作回归，不用训练集拟合结果宣称泛化。
5. 双方使用同一新搜索，分别比较等节点和等时间。沿用128对初筛，独立512对验证及512对复核；对gen9/HCE均需得分≥52%、成对95%CI下界>50%、无截断，才替换冠军。

入口 `scripts/train_search_gen9.sh`，默认6轮、保存第1/3/6轮与验证loss最佳模型；初筛只选一个候选，独立等节点及单线程100ms等时间门槛均通过才晋升。`--replay`可加入已有数据。旧 `train_from_gen9.sh`不用于本轮。

上传 `artifacts/gomoku-search-gen9.tgz`，解压生成 `gomoku-next/`。启动：

```bash
. "$HOME/.cargo/env" && cd /gemini/code/gomoku-next && THREADS=6 RUN_DIR=/gemini/output/search-gen9-001 CARGO_TARGET_DIR=/gemini/output/target UV_PROJECT_ENVIRONMENT=/gemini/output/search-gen9-venv uv run --frozen --extra cu128 bash scripts/train_search_gen9.sh
```

## 环境与产物

```bash
# 选择一个PyTorch环境
uv sync --frozen --extra cpu
# NVIDIA云端使用：uv sync --frozen --extra cu128
```

云端先 `. "$HOME/.cargo/env"`，项目 `/gemini/code/gomoku-next`；输出与编译缓存放 `/gemini/output`，通常6线程。GPU用于训练，自对弈／竞技主要消耗CPU；不要只看GPU利用率。

上传最新源码与 `artifacts/cloud-gen9.nnue`、配套 `cloud-gen9.pt`，校验匹配与SHA。每次使用新输出目录，保留数据、配置、候选、训练日志和对局JSON；网页不会自动取得新网络。

试验期间固定教师算法，搜索加速另行验证。loss下降不能代替棋力晋升。
