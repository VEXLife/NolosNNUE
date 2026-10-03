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
target/release/nolos-nnue --weights artifacts/cloud-gen9.nnue
```

The browser defaults to handcrafted evaluation; load a network manually. Refresh after rebuilding WASM. Deploy `web/` to any static host.

Generation 9 remains the recommended model. New search fixes missed tactical sequences; overall strength gains remain unverified. Previous spatial and fine-tuning trials failed promotion. The next experiment is a small legacy fine-tune with improved search labels and sampling, described in [training](docs/training.md).

[Protocol](docs/protocol.md) · [Network format](docs/network.md) · [Experiment history](docs/history.md)

Supports 5–20 square boards and freestyle, standard, and Renju rules; training currently accepts freestyle only. Selective search is not an exhaustive proof solver. External engines are references and opponents only; their weights and data are not used in bootstrap training.

MIT license.
