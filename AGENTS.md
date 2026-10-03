# 接手入口

先读本文件。做训练再读 `docs/training.md`；协议／网络按需查对应文档。历史结果在 `docs/history.md`，无需逐条重读。

## 当前状态

- Rust原生与WASM共用引擎；入口 `src/protocol.rs`，搜索 `src/search.rs`，训练 `trainer/`，网页 `web/`。
- 当前模型 `artifacts/cloud-gen9.nnue`，配套 `.pt` 用于微调。搜索最新版本地二进制 `target/counter-audit/release/`；默认qdepth=1、selective关闭。云端尚未更新源码。
- 新搜索已通过三个用户杀棋案例、17/31手VCF及原生/WASM检查；整体棋力提升尚未证明。当前准备调整采样后试训，没有运行中的新训练任务。
- `scripts/train_from_gen9.sh`仍是旧spatial流程，不应直接当作本轮试训入口。本轮入口为 `scripts/train_search_gen9.sh`；`package_gen9.py`已改为本轮legacy打包器。

## 工作约束

- 保留工作区既有修改；未经要求不提交、重置、发布或启用子agent。
- `references/`只作研究、已忽略，不提交、不照抄。外部引擎权重仅用于对战，不能混入自举训练。
- 文档只更新现有入口、方案或历史表，不为每次实验再建Markdown。详细命令、数据、SHA和日志放实验产物，Markdown只保留结论及路径。

## 验证

```bash
cargo test --lib --test core
cargo build --release --bins
bash scripts/build-web.sh
python3 scripts/check_protocol.py
node scripts/check_wasm.mjs web/nolos_nnue.wasm artifacts/cloud-gen9.nnue
```

本机release测试曾遇到工具链LTO冲突；debug测试和release bins正常。按改动选检查，不重复跑无关历史实验。

## 云端操作

用户此前已授权使用agent-browser操作Chromium，CDP端口9222。具体页面／日志读取方法见忽略目录 `.agent/README.md`。
启动命令必须先 `. "$HOME/.cargo/env"`；项目 `/gemini/code/gomoku-next`，输出 `/gemini/output`，通常THREADS=6。新任务先核实代码包、模型及挂载路径。
