# NolosNNUE 网页

[English](README.md) | 简体中文

本目录是纯静态站点。先运行仓库根目录的 `scripts/build-web.sh`，生成 `web/nolos_nnue.wasm`，再将本目录部署到 HTTPS 静态托管。无需 Node.js，也无需后端、共享内存或 COOP/COEP 头。

本地预览：

```sh
python -m http.server 8080 --directory web
```

访问 `http://localhost:8080`。浏览器不支持直接通过 `file://` 加载 Worker / WASM。

棋盘使用 Rust 引擎的 `YXSTATUS` 渲染；人工落子使用 `PLAY`；对弈搜索使用 `BOARD ... DONE`；分析使用 `YXSUGGEST`。这些命令通过 Worker 调用同一协议实现，网页没有单独的棋规或搜索算法。

支持本地 `.nnue` 文件与 HTTP(S) URL；URL 需要服务端允许 CORS。权重在浏览器本地校验，失败时保留原评估器。恢复 HCE 后无需任何神经网络文件。

导出的 JSON 棋谱记录棋盘大小、规则及按顺序排列的 `[交点索引, 实际颜色]`，索引为 `y * size + x`，黑方为 `1`、白方为 `2`。导入会进入分析模式。
