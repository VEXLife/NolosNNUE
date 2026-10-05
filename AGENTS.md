# 接手入口

先读本文件。做训练再读 `docs/training.md`；协议／网络按需查对应文档。历史结果在 `docs/history.md`，无需逐条重读。

## 当前状态

- Rust原生与WASM共用引擎；入口 `src/protocol.rs`，搜索 `src/search.rs`，训练 `trainer/`，网页 `web/`。
- 当前对战模型仍是 `artifacts/cloud-gen9.nnue`；新训练完全从HCE开始，入口 `scripts/train_hce.sh`，打包 `scripts/package_hce.py`，新包不含权重／旧数据。
- 默认30代×4096盘，学习器从验证最佳检查点继续、10轮早停、2.5%标签软化、每步5万节点、杀棋收尾限采样、四代回放、每代128对竞技、52%得分晋升（不复核）；配置和续跑见 `docs/training.md`。
- 搜索已修复PV节点LMR漏杀；默认qdepth=1、selective关闭。最近初始化对照未晋升，历史只需按需查 `docs/history.md`。
- 旧spatial启动、refine、sweep、deep实验脚本已移除，原件保存在忽略的 `.agent/obsolete-training-20261003.tgz`。保留网络格式、检查工具和可用的微调入口。

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
项目 `/gemini/code/gomoku-next`，输出 `/gemini/output`，通常THREADS=6。新任务先核实代码包、模型及挂载路径。
