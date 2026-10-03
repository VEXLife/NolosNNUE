# 实验历史摘要

以下为已完成结果，不是当前启动建议。原始数据／日志为依据；不同搜索和预算的得分不能直接横比。

## 训练

| 实验 | 结果 | 证据／入口 |
|---|---|---|
| 初始HCE自举 | 候选对HCE42.58%，未晋升 | `artifacts/generation-0.{training,arena,manifest}.json` |
| 用户旧云端模型复核 | gen9对旧冠军52.00%、对HCE62.55%，推荐保留gen9 | `artifacts/cloud-gen9.manifest.json`、`cloud-gen9.arena-*.json` |
| 初始化／学习率等对照 | 未证明比旧冠军强 | `artifacts/cloud-experiments.json`、`cloud-training-audit.json` |
| spatial长训练 | 前两代对gen9 40.33%／38.96%，无晋升；CPU自对弈占约87% | 云任务761241542181842944；旧流程`train_from_gen9.sh` |
| refine复用数据 | 三候选初筛42.58%／44.14%／39.06%，均失败 | 云任务761378938156281856；`scripts/refine_gen9.py` |
| 512盘80万节点深搜索 | 独立1024盘50.15%／49.56%，无晋升 | 云任务761384768101138432；`scripts/deep_gen9.py` |
| 固定数据增训 | 唯一正式候选48.00%，CI46.3%–49.7%，无晋升 | 云任务761404033562820608；`scripts/sweep_gen9.py` |

增训的10/30轮还同时改变余弦调度周期，不能把差异完全归因于训练量。此前loss下降没有转化成已验证棋力提升。

## 搜索

方向几何预计算与增量成五缓存曾分别降低固定节点耗时约13.5%／11.8%；后续战术检查又增加成本。这些是阶段测量，不代表最新版合计提速。证据：`artifacts/search-speed-audit.json`、`threat-cache-audit.json`。

当前 `target/counter-audit/release/`：纯强制防守延伸，反冲四消耗预算；默认qdepth=1，静态总长度和TT预算隔离；新增可验证五手短杀。主搜索仍选择性限宽，不是完整必胜证明器。

| 棋谱（15×15自由棋） | 冷启动结果，第9代NNUE | 证据 |
|---|---|---|
| `h8g8i7g9g7i9h7f7h9h6j7k7i8g10j9` | 白−M16，126623节点约1.2秒；防守g6/k10/g11/g12均通过 | `artifacts/counter-previous-position.json` |
| `h8i7g7i9h6f8i8g6j4i5h9h7i10j8g10` | 白−M18，621492节点约6.8秒；j7/f11后黑+M17 | `artifacts/counter-regression-after.json` |
| `h8g7i7g9h6j8g8h7j6i6k7k5l8i5k9j5l5k4` | 黑−M18，84025节点约1.1秒 | `artifacts/nnue-readiness-position.json`、`nnue-readiness-wasm.json` |

36项Rust测试、原生/WASM与17/31手VCF检查曾通过；改动后按需复测。`scripts/check_threat_regression.py`支持`--winner white`。

最新版六个普通局面300ms请求完成深度5/5/5/4/4/5；Rapfi历史参考14–24层。强制延伸计数、网络及资源不同，不能单凭名义深度比较棋力；速度仍有明显差距。证据：`artifacts/counter-time-after.json`、`rapfi-depth-reference.json`。

参考克隆在忽略的 `references/`，未复制代码。清理前的完整Markdown保存在本地忽略文件 `.agent/docs-before-cleanup-20261003.tar.gz`，仅需追溯细节时解压。
