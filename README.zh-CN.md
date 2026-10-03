# NolosNNUE

[English](README.md)。Rust五子棋引擎，支持原生／浏览器WASM、自对弈和NNUE训练。接手开发先读 [AGENTS.md](AGENTS.md)。

## 启动

需要Rust 1.88以上、WASM目标、Python；训练依赖由uv管理。

```bash
cargo build --release --bins
bash scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

打开 http://localhost:8000 。原生入口：

```bash
target/release/nolos-nnue --weights artifacts/cloud-gen9.nnue
```

官方Rust工具链先执行 `rustup target add wasm32-unknown-unknown`；Arch可安装匹配的 `rust`、`rust-wasm`。网页默认HCE，可手动加载 `.nnue`；刷新页面才能使用新WASM。

## 当前状态与文档

推荐模型是第9代，新搜索能识别此前漏掉的长杀棋；尚未证明整体棋力达到Rapfi。此前spatial与多轮微调均未晋升，现在准备新搜索标签的小规模legacy试训。

- [训练方案](docs/training.md)：当前试训计划、环境与评测要求。
- [协议](docs/protocol.md)、[网络格式](docs/network.md)：实现规范，按需查阅。
- [历史摘要](docs/history.md)：已完成实验及证据路径。

自由／标准／连珠规则，5–20路方形棋盘；训练器只接受自由五子棋。搜索有候选截断与启发式剪枝，杀棋评分不等同完整穷举证明。外部参考引擎只用于研究和对战，自举训练不使用其数据或权重。

`web/`可直接部署到静态托管；无需后端。MIT许可。
