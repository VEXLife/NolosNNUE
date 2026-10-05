# NolosNNUE

[简体中文](README.zh-CN.md)

A Rust Gomoku engine with native and browser WASM frontends, self-play, and NNUE training. New agents should start with [AGENTS.md](AGENTS.md).

```sh
cargo build --release --bins
bash scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

Requires Rust 1.88+ and the `wasm32-unknown-unknown` target. Open http://localhost:8000, or run:

```sh
target/release/nolos-nnue
```

The browser defaults to handcrafted evaluation; load a network manually. Refresh after rebuilding WASM. Deploy `web/` to any static host.

Generation 9 remains the existing playing model. The current training run starts from HCE with randomly initialized NNUE, larger self-play cohorts and independently gated promotion. See [training](docs/training.md). The HCE upload package contains no pretrained weights.

[Protocol](docs/protocol.md) · [Network format](docs/network.md) · [Experiment history](docs/history.md)

Supports 5–20 square boards and freestyle, standard, and Renju rules; training currently accepts freestyle only. Selective search is not an exhaustive proof solver. External engines are references and opponents only; their weights and data are not used in bootstrap training.

MIT license.
