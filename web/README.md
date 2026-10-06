# 网页

项目根目录执行：

```bash
bash scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

打开 http://localhost:8000 。不能从file://运行Worker/WASM；部署只需静态托管 `web/`。

网页通过同一Rust协议引擎进行下棋／分析，不实现另一套棋规。默认HCE，可加载本地或允许CORS的URL网络；坏权重不替换旧网络。更新WASM后刷新页面重建Worker。

WASM构建默认启用`simd128`，需要浏览器支持WebAssembly SIMD；NOLOS001的FP32累加器和价值头使用四路向量运算，价值头仍按原顺序求和。Worker加载WASM时重新验证HTTP缓存。本次定节点对照脚本与报告归档在`.agent/nonquant-speed-20261006/`。

候选着按位集合枚举，落点评分合并双颜色计算，撤销时恢复受影响的成五缓存。Worker采用约16毫秒工作片、每批32节点，减少计时器调度开销，片间处理停止命令。

默认3秒，复杂杀棋复测可选30秒。胜率显示是估分的sigmoid，不是校准概率。棋谱形如`h8g7g12f10`，支持旋转／镜像及分析不落子。
