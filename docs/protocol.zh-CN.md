# Yixin 协议支持

[English](protocol.md) | 简体中文
依据 [Yixin-protocol 原文](https://github.com/accreator/Yixin-protocol) 与 [Gomocup 基础协议](https://plastovicka.github.io/protocl2en.htm) 实现，并核对本地 Yixin-Board 的 `send_board` 和分析信息解析代码。大小写不敏感，接受 CRLF/LF；坐标从零开始，`p = y * size + x`。

原生和 WASM 都调用 `src/protocol.rs` 的 Engine。浏览器 JS 不翻译成另一套棋类 API，仅调用命令入口和承载原本由文件系统负责的权重字节上传。

## 标准与原文扩展

| 命令 | 行为 |
| --- | --- |
| `START N` | 初始化 5..20 方形棋盘；答 `OK`，不落子，保留规则和网络 |
| `RESTART` | 清空当前位置与置换表；答 `OK` |
| `RECTSTART W,H` | 仅支持 W=H，否则 `ERROR` |
| `ABOUT` | 输出名字、版本和作者 |
| `BEGIN` | 在空棋盘执黑搜索并落子 |
| `TURN X,Y` | 放置对手棋子，搜索并输出本方 `X,Y` |
| `BOARD` + 多行 `X,Y,field` + `DONE` | 替换棋盘后搜索并落子 |
| `YXBOARD` + 同上 | 替换棋盘，**不搜索，不回复着法** |
| `PLAY X,Y` | 只提交本方着法，回显 `X,Y`，不搜索 |
| `TAKEBACK X,Y` | 移除指定棋子；答 `OK` 或 `ERROR` |
| `YXSTOP` | 中断搜索并输出一次着法；无搜索时静默 |
| `YXHASHCLEAR` | 清空置换表；静默 |
| `YXSHOWFORBID` | 连珠黑方禁手：`FORBID X1Y1X2Y2... .`，实际输出无点前空格，每坐标两位；非连珠答 `ERROR` |
| `END` | 立即终止，不再输出 |

`field=1` 表示引擎方，`field=2` 表示对手。按落子顺序输入时第一颗棋的颜色为黑，可据此还原实际黑白。连珠需要交替的历史顺序。无禁规则的非交替顺序 `BOARD` 用双方棋子数量判断引擎执黑／白；不接受重复坐标或 field=3。输入先暂存，合法 `DONE` 才替换，错误不会破坏原棋盘。

搜索状态有独立棋盘副本。中断时只在协议主棋盘提交最佳着法，不会提交尚未完成搜索的变化路径。`START`、`RESTART` 和新的 `BOARD` 会取消已有搜索。

| `INFO` 参数 | 支持 |
| --- | --- |
| `rule` | **Yixin 0=自由、1=标准、2=连珠**，不是旧 Gomocup 位掩码；不支持值产生延迟错误 |
| `timeout_turn` | 毫秒；0 立即返回静态棋形排序着法 |
| `time_left`、`time_increment` | 根据剩余时间分配搜索预算 |
| `max_depth` | 正数限制最大迭代深度；非正数取消该人为限制 |
| `max_node` | 正数限制总节点数；非正数取消节点限制 |
| `hash_size` | **KB**，不超过 64 MiB；0 关闭表 |
| `max_memory` | 降低置换表预算；不是整个进程的硬内存限制 |
| `thread_num` | 一个搜索线程，满足任意正数上限；原生还有仅负责输入的线程 |
| `thread_split_depth` | 无任务分割，忽略 |
| `show_detail` | 正数启用 Yixin 日志统计与 `MESSAGE REALTIME` 主变化；0 关闭 |
| 其他 INFO | 静默忽略；不主动 pondering |

分析输出兼容本地 Yixin-Board：`INFO NUMPV 1`、`INFO PV 0`、`INFO DEPTH`、`INFO NODES`、`INFO EVAL`、`INFO WINRATE`、`INFO BESTLINE`、`INFO PV DONE`。WINRATE 是评估值的 sigmoid 映射，不是经外部比赛校准的概率。必胜分以 `+M`/`-M` 输出，但选择性搜索不等同完整形式证明。

## 本项目扩展

| 命令 | 行为 |
| --- | --- |
| `YXGO` | 在当前棋盘以引擎方搜索并落子 |
| `YXSUGGEST` | 分析但不落子，最终输出 `SUGGEST X,Y`；停止也只建议 |
| `YXSTATUS` | `MESSAGE STATUS {JSON}`，包括大小、规则、下方、赢家、棋盘及历史 |
| `YXLOADNNUE PATH` | 原生从文件加载，成功答 `OK`；WASM 由宿主上传字节 |
| `YXUNLOADNNUE` | 恢复 HCE，清空表，答 `OK` |
| `YXEVAL` | `MESSAGE EVAL 数值`，引擎方视角 |
| `YXSHOWINFO` | 输出引擎名称、版本、评估器，并告知 GUI 最大搜索线程数与哈希容量 |
| `YXSHOWHASHUSAGE` | 输出已分配置换表容量 |

改变评估器需先停止搜索；错误权重不替换旧网络。未实现的附加命令，例如数据库、`YXNBEST` 多 PV、Swap2/Soosõrv 开局协商、阻断路径，返回 `UNKNOWN`，不会假装成功。支持原文协议核心不代表实现 Rapfi 对 GUI 的全部私有扩展。

浏览器 ABI 导出 `engine_init`、`engine_alloc`、`engine_free`、`engine_command`、`engine_tick`、`engine_load_weights`，宿主提供输出回调和单调时钟。Worker 定期让出执行，保证 `YXSTOP` 无需共享内存即可进入相同协议状态机。
