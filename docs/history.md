# 实验历史摘要

以下为已完成结果，不是当前启动建议。原始数据／日志为依据；不同搜索和预算的得分不能直接横比。

## 训练

| 实验 | 结果 | 证据／入口 |
|---|---|---|
| 初始HCE自举 | 候选对HCE42.58%，未晋升 | `artifacts/generation-0.{training,arena,manifest}.json` |
| 用户旧云端模型复核 | gen9对旧冠军52.00%、对HCE62.55%，推荐保留gen9 | `artifacts/cloud-gen9.manifest.json`、`cloud-gen9.arena-*.json` |
| 初始化／学习率等对照 | 未证明比旧冠军强 | `artifacts/cloud-experiments.json`、`cloud-training-audit.json` |
| spatial长训练 | 前两代对gen9 40.33%／38.96%，无晋升；CPU自对弈占约87% | 云任务761241542181842944；旧启动已归档 |
| refine复用数据 | 三候选初筛42.58%／44.14%／39.06%，均失败 | 云任务761378938156281856；脚本已归档 |
| 512盘80万节点深搜索 | 独立1024盘50.15%／49.56%，无晋升 | 云任务761384768101138432；脚本已归档 |
| 固定数据增训 | 唯一正式候选48.00%，CI46.3%–49.7%，无晋升 | 云任务761404033562820608；脚本已归档 |
| 新搜索256盘微调 | 2246样本；6候选均漏第三个杀棋，无竞技／晋升；已定位PV减深漏杀并修复；22/32单元在新数据饱和 | 云任务761466206863474688；`artifacts/search-gen9-analysis.json` |
| LMR修复后256盘微调 | 4820原始／1852训练验证样本；纯搜索第6轮独立1024盘得分49.56%，CI48.4%–50.7%，未晋升；混合第3轮漏第二个杀棋 | 云任务761494023797272576；`artifacts/search-gen9-002-cloud.log` |
| 初始化三组对照 | 复用1852样本，三学习率各40轮；恢复23个单元候选初筛50.39%、验证49.80%（CI48.6%–51.0%），无晋升；从零未追上gen9 | 云任务761512746839687168；`artifacts/init-compare-cloud.log` |
| hce-local-002固定数据对照（2026-10-05） | 复用001～004代185137局面；仅降学习率未过线；lr=0.001、outcome_weight=0.3候选对教师001初筛52.54%，独立512盘53.22%（CI51.42%–55.03%）。原运行配置及冠军未改动 | `.agent/teacher001-study-20261005/study-summary.json`；模型在`legacy-outcome03/candidate.nnue` |
| NOLOS002同数据结构／搜索对照（2026-10-05） | 纯价值／策略辅助版原搜索46.48%／46.88%；沿用NOLOS001排序、限宽及减深后初筛52.34%／53.32%，独立512盘51.66%／49.90%，均未确认超过教师001。原搜索组合拖累约6个百分点；等时间未测 | `.agent/teacher001-study-20261005/study-summary.json`；隔离训练器及搜索引擎在同目录 |

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
