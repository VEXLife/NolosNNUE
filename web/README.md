# NolosNNUE web interface

English | [简体中文](README.zh-CN.md)

This directory is a static website. Run `scripts/build-web.sh` from the repository root to generate `web/nolos_nnue.wasm`, then deploy this directory to an HTTPS static host. No Node.js, backend, shared memory, or COOP/COEP headers are required.

Preview locally:

```sh
python -m http.server 8080 --directory web
```

Open `http://localhost:8080`. Browsers cannot load the Worker and WASM directly through `file://`.

The board renders the Rust engine's `YXSTATUS`; human moves use `PLAY`; game searches use `BOARD ... DONE`; analysis uses `YXSUGGEST`. The Worker sends these commands to the same protocol implementation. The web interface does not implement separate game rules or search algorithms.

Load a local `.nnue` file or an HTTP(S) URL. Remote URLs require the server to allow CORS. Weights are validated locally in the browser; a failed load preserves the existing evaluator. Restoring HCE requires no neural network file.

Exported JSON positions contain the board size, rules, and chronological `[intersection index, actual color]` pairs. The index is `y * size + x`; black is `1` and white is `2`. Importing a position switches to analysis mode.
