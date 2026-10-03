# 网页

项目根目录执行：

```bash
bash scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

打开 http://localhost:8000 。不能从file://运行Worker/WASM；部署只需静态托管 `web/`。

网页通过同一Rust协议引擎进行下棋／分析，不实现另一套棋规。默认HCE，可加载本地或允许CORS的URL网络；坏权重不替换旧网络。更新WASM后刷新页面重建Worker。

默认3秒，复杂杀棋复测可选30秒。胜率显示是估分的sigmoid，不是校准概率。棋谱形如`h8g7g12f10`，支持旋转／镜像及分析不落子。
