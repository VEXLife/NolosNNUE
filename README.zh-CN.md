# NolosNNUE

[English](README.md) | 简体中文
一个可重复的五子棋自举训练实验：从手写棋形评估（HCE）开始，用自己的搜索和自对弈生成数据，训练 NNUE，再通过独立对战决定是否晋升。**不下载外部棋谱、策略标签或预训练权重。**

Rust 原生引擎和浏览器 WASM 引擎共用棋规、评估、搜索与 Yixin 协议状态机。网页只传输命令、加载权重和显示结果。

**当前是实验引擎，并未证明达到 Rapfi 等顶级引擎的强度。** 已附上的首轮候选在 256 局对战中对 HCE 得分率为 42.58%，没有通过晋升门槛。网页默认使用 HCE，样例权重仅供验证加载与训练流程。

## 快速开始

Arch Linux 使用匹配版本的系统 Rust 和 WASM 标准库：

```bash
paru -Syu rust rust-wasm uv nodejs
cargo build --release --bins
scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

打开 <http://localhost:8000>。支持执黑／执白、摆棋分析、悔棋、停止、禁手显示、棋谱导入导出和本地／URL 加载 `.nnue`。所有计算在浏览器本地完成。部署时只需上传 `web/`，不需要 Python 服务端、WASI 或特殊线程隔离响应头。

其他平台可使用 Rust 官方工具链：

```bash
rustup target add wasm32-unknown-unknown
scripts/build-web.sh
```

原生引擎通过 stdin/stdout 通信：

```bash
./target/release/nolos-nnue
./target/release/nolos-nnue --weights artifacts/generation-0.nnue
```

在 Yixin-Board 启动时的工作目录放置名为 `engine` 的可执行文件或链接，例如在本项目根目录：

```bash
ln -s target/release/nolos-nnue engine
```

需要默认加载网络时，把 `engine` 换成一个调用 `nolos-nnue --weights /绝对路径/网络.nnue` 的脚本。也可以通过协议 `YXLOADNNUE /绝对路径/网络.nnue` 加载。`Yixin-Board/` 只作为本地参考，已排除于 Git 提交。

## 大规模自举训练

Python 环境由 uv 管理。选择一个互斥的 PyTorch extra：CPU 用 `cpu`，NVIDIA GPU 用 `cu128`（CUDA 12.8 wheel，需要兼容的 NVIDIA 驱动）。锁文件支持两者，不再强制安装 CPU 版。

NVIDIA 机器使用：

```bash
uv sync --frozen --extra cu128
uv run --frozen --extra cu128 -m trainer.bootstrap \
  --run-dir runs/large-001 \
  --generations 10 --games 8192 --epochs 40 --pairs 256 \
  --nodes 20000 --depth 6 --threads 8 --seed 42 \
  --train-device cuda --train-batch-size 4096 \
  --train-workers 4 --train-precision auto
```

GPU 训练使用预打包稀疏数据，由数据加载 worker 向量化构建 dense batch，使用 pinned memory 和非阻塞上传。支持的设备启用 TF32，自动精度在支持 BF16 时使用 BF16 AMP，否则使用 FP32。训练循环避免逐 batch 的 `.item()` 同步，并报告每个 epoch 的吞吐。上述 batch 和 worker 数是调优起点，不是本机实测最优值。CPU 默认确定性训练；CUDA 默认优先吞吐，需要严格可复现时加 `--train-deterministic --train-precision fp32`，可能降低速度。单独训练使用 `--deterministic --precision fp32`。

**自对弈与竞技评测仍在 CPU 执行。** 这些阶段 GPU 会闲置，小网络也可能无法占满大型 GPU。开发机器没有 NVIDIA GPU，尚无 CUDA 性能实测；提高 CPU 搜索资源和观察训练吞吐同样重要。

这是长时间实验配置，不是对“必然变强”的承诺。先用下面的较小配置确认本机环境和全流程：

```bash
uv sync --frozen --extra cpu
uv run --frozen --extra cpu -m trainer.bootstrap \
  --run-dir runs/smoke-001 \
  --generations 2 --games 16 --epochs 3 \
  --pairs 4 --nodes 512 --depth 2 --threads 2
```

冒烟配置不会晋升网络，因为晋升至少需要 32 个完整开局对。运行目录必须不存在，避免覆盖已有实验。

每代的流程：

1. 当前冠军生成自对弈。最初的冠军是 HCE，网络参数从随机初始化开始。
2. 训练最近几代数据的 NNUE。标签混合搜索胜率和真实对局结果；被截断的对局不伪装成和棋。
3. 在新生成的开局上对战，每个开局交换双方执黑／执白。训练、验证与竞技评测使用分开的随机种子；训练／验证按整盘对局划分。
4. 候选需同时超过上一代冠军和固定 HCE 基线：得分至少 55%，近似 95% 开局对置信区间下界超过 50%，没有截断对局。失败候选不成为下一代教师。
5. 保存命令、种子、数据与权重 SHA-256、训练日志、竞技评测和晋升结果。

主要输出：

```text
runs/large-001/
  config.json
  summary.json
  generation-000/
    selfplay.jsonl
    candidate.nnue
    candidate.pt
    candidate.training.json
    arena-0.json
    manifest.json
    *.log
  champion.nnue       # 仅成功晋升后才存在
  champion.pt
```

中断后，用相同参数、相同目录加上 `--resume-run` 继续。已完成的阶段会校验 SHA-256 后跳过，未完成的阶段重跑；不在单盘自对弈或训练 epoch 中间恢复。大实验先留意磁盘与内存，`--games`、`--threads`、`--replay-generations` 可降低资源使用。CPU 是默认训练设备；GPU 运行需选择 CUDA extra 并显式传入 `--train-device cuda`。

### 分步运行

```bash
# 第一批数据只能由 HCE 生成
./target/release/selfplay --weights hce \
  --games 2048 --depth 4 --nodes 8000 --threads 8 \
  --seed 1 --output runs/hce.jsonl

# 从随机参数训练；--resume 可接续本项目生成的 .pt
uv run --frozen --extra cu128 -m trainer.train \
  --data runs/hce.jsonl --output runs/candidate.nnue \
  --epochs 40 --seed 42 --device cuda --batch-size 4096 \
  --workers 4 --precision auto

# 对战固定基线，双方搜索设置一致
./target/release/arena \
  --candidate runs/candidate.nnue --baseline hce \
  --pairs 256 --depth 4 --nodes 8000 --threads 8 \
  --seed 900000 --output runs/arena.json
```

分步运行前自行创建 `runs/`。`selfplay` 和 `arena` 支持规则 0/1/2；当前训练器只接受自由五子棋（0），避免混合不同规则但未编码规则的训练数据。网络结构本身不接收规则特征，因此仅将已训练网络的棋力结论用于对应训练规则。

## 引擎设计与边界

- 5～20 路方形棋盘；自由五子棋、恰好五连的标准五子棋、连珠禁手。连珠使用递归真三判断、不同四组去重和同时成五的优先规则。特殊交换开局协商不在当前范围内。
- 可恢复的显式栈 Alpha-Beta、迭代加深、置换表、棋形排序、killer/history 排序，以及连续冲四／强制防守静态搜索。候选位置限于已有棋子附近两格，并对非强制分支限宽；这是选择性搜索，不是完整必胜证明器。
- 六格方向棋形使用两位编码：空、黑、白、边界。反向棋形规范化，共 4096 个索引空间。共享 32 维嵌入与黑白双累加器，裁剪 ReLU 后输出反对称局面值和先手项。落子／撤子增量更新；加载网络后静态评估使用网络，战术排序仍使用手写棋形。
- `.nnue` 是本项目的 `NOLOS001` 格式，带架构信息和 FNV-1a 校验，约 513 KiB。**不兼容 Rapfi / Stockfish 的权重格式。**
- 一个搜索线程；原生输入线程接收中断，浏览器 Worker 在短工作片段之间处理命令。`YXSTOP` 返回已完成搜索迭代的最佳着法，搜索副本不会污染主棋盘。

协议实现与支持表见 [docs/protocol.md](docs/protocol.zh-CN.md)，网络格式见 [docs/network.md](docs/network.zh-CN.md)，首轮实验见 [docs/experiment.md](docs/experiment.zh-CN.md)。

## 验证

```bash
cargo test
cargo build --release --bins
scripts/build-web.sh
python3 scripts/check_protocol.py
node scripts/check_wasm.mjs web/nolos_nnue.wasm artifacts/generation-0.nnue

# 用生成数据比较 PyTorch、原生 Rust 与 WASM 的评估值
uv run --frozen --extra cpu -m scripts.check_network \
  --data runs/hce.jsonl --weights runs/candidate.nnue --samples 100
```

数值一致性检查需要 `.nnue` 对应的 `.pt`；首轮原始数据可按 [实验记录](docs/experiment.zh-CN.md) 重建。GitHub Actions 包含小型端到端检查。

## 在线部署

任意静态托管服务均可部署 `web/`。GitHub Pages 的 `pages.yml` 只允许手动触发：在仓库 Settings → Pages 选择 GitHub Actions，再在 Actions 中选择 `seed` 分支运行 “Deploy static WASM website”。GitHub 仅在默认分支包含该工作流时显示手动触发入口；若 `master` 仍为默认分支且没有工作流，需要先将工作流加入默认分支，或自行决定更改默认分支。本项目不会自动更改 `master`、推送或部署。

## Rapfi 与 KataGomo 的关系

“Rapfi 利用 KataGomo 的知识”是对的，但“用 KataGomo 参数初始化 NNUE”并不准确。[Rapfi 论文 §4.1–4.2](https://arxiv.org/html/2503.13178v1#S4) 描述的是使用 KataGomo 生成的约 3080 万个局面、价值和策略标签进行监督训练，并用同一数据集训练的 ResNet 作为蒸馏教师。这与直接继承参数不同。本项目的对比实验是用自己的 HCE 搜索启动这个循环。

## 许可

MIT。全部引擎、训练器与网页代码为本项目实现；协议与算法资料作为参考来源，没有复制或提交 Yixin-Board 源代码。
