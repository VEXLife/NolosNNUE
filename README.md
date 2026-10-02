# NolosNNUE

English | [简体中文](README.zh-CN.md)

A reproducible Gomoku bootstrap experiment: start with a handcrafted evaluation (HCE), generate data using the engine's own search and self-play, train an NNUE, then promote it only after independent matches. **No external game records, policy labels, or pretrained weights are downloaded.**

The native Rust engine and browser WASM engine share the rules, evaluation, search, and Yixin protocol state machine. The website transports commands, loads weights, and displays results.

**This is an experimental engine; strength comparable to Rapfi or other leading engines has not been demonstrated.** The included first-generation candidate scored 42.58% against HCE over 256 games and failed promotion. The website defaults to HCE; the sample weights demonstrate loading and training.

## Quick start

On Arch Linux, install matching system Rust and WASM standard libraries:

```bash
paru -Syu rust rust-wasm uv nodejs
cargo build --release --bins
scripts/build-web.sh
python3 -m http.server 8000 --directory web
```

Open <http://localhost:8000>. The website supports playing either color, position analysis, undo, stopping searches, forbidden-move display, game import/export, and loading `.nnue` files locally or by URL. All computation runs in your browser. Deploy the contents of `web/` to any static host; no Python backend, WASI, or special cross-origin isolation headers are required.

On other platforms, use the official Rust toolchain:

```bash
rustup target add wasm32-unknown-unknown
scripts/build-web.sh
```

The native engine communicates through stdin/stdout:

```bash
./target/release/nolos-nnue
./target/release/nolos-nnue --weights artifacts/generation-0.nnue
```

Yixin-Board expects an executable named `engine` in its launch working directory. For example, from this project's root:

```bash
ln -s target/release/nolos-nnue engine
```

To load weights at startup, replace the symlink with a script invoking `nolos-nnue --weights /absolute/path/network.nnue`. Alternatively, send `YXLOADNNUE /absolute/path/network.nnue`. The local reference checkout `Yixin-Board/` is excluded from Git.

## Large-scale bootstrap training

Python dependencies are managed by uv. Choose exactly one PyTorch extra: `cpu` for CPU-only training, or `cu128` for NVIDIA CUDA 12.8 wheels. These extras are mutually exclusive; the lockfile supports both and does not force CPU PyTorch on a GPU machine. CUDA wheels require a compatible NVIDIA driver.

For an NVIDIA machine:

```bash
uv sync --frozen --extra cu128
uv run --frozen --extra cu128 -m trainer.bootstrap \
  --run-dir runs/large-001 \
  --generations 10 --games 8192 --epochs 40 --pairs 256 \
  --nodes 20000 --depth 6 --threads 8 --seed 42 \
  --train-device cuda --train-batch-size 4096 \
  --train-workers 4 --train-precision auto
```

GPU training uses prepacked sparse datasets, vectorized dense batch construction in data-loader workers, pinned memory, and nonblocking transfers. Supported devices use TF32 and automatic BF16 mixed precision; automatic precision falls back to FP32 when BF16 is unavailable. The training loop avoids per-batch `.item()` synchronization and reports epoch throughput. Batch size and worker count are starting points to tune for your hardware, not measured optimal settings. CPU training is deterministic by default. CUDA prioritizes throughput; use `--train-deterministic --train-precision fp32` when strict reproducibility matters, at a possible performance cost. For standalone training, use `--deterministic --precision fp32`.

**Self-play and arena matches still run on the CPU.** The GPU can be idle during those stages, and this relatively small network may not saturate a large GPU even during training. No CUDA performance measurements were made on the development machine. Increasing CPU search resources and profiling training throughput matter as much as choosing a GPU.

First check the complete pipeline with a small CPU run:

```bash
uv sync --frozen --extra cpu
uv run --frozen --extra cpu -m trainer.bootstrap \
  --run-dir runs/smoke-001 \
  --generations 2 --games 16 --epochs 3 \
  --pairs 4 --nodes 512 --depth 2 --threads 2
```

This smoke configuration cannot promote a network: promotion requires at least 32 complete opening pairs. Use a new run directory to avoid overwriting an existing experiment. Larger experiments do not guarantee improvement.

Each generation:

1. Generates self-play with the current champion. Initially the champion is HCE, and the network starts from random parameters.
2. Trains on recent generations. Targets combine search win probability and actual game outcomes; truncated games are not treated as draws.
3. Evaluates on independently generated openings, playing both colors for each opening. Training, validation, and arena evaluation use separate seeds; training/validation split by whole games.
4. Promotes only if the candidate beats both the previous champion and fixed HCE: at least 55% score, an approximate 95% opening-pair confidence interval with lower bound above 50%, and no truncated games. Rejected candidates never become teachers.
5. Records commands, seeds, data and weight SHA-256 hashes, training logs, match results, and promotion decisions.

Main outputs:

```text
runs/large-001/
  config.json
  summary.json
  generation-000/
    selfplay.jsonl
    candidate.nnue
    candidate.pt
    candidate.training.json
    arena-0.json
    manifest.json
    *.log
  champion.nnue       # Only exists after successful promotion
  champion.pt
```

To resume, repeat the same command with the same directory and parameters, adding `--resume-run`. Completed stages are checked against their SHA-256 hashes and skipped; incomplete stages restart. Recovery is not available within an individual game or training epoch. Monitor disk and RAM usage; reduce `--games`, `--threads`, or `--replay-generations` if necessary. CPU is the default training device; GPU runs must explicitly select `--train-device cuda` and the CUDA extra.

### Run stages separately

Create `runs/` before these commands:

```bash
# Generate the initial data using HCE alone.
./target/release/selfplay --weights hce \
  --games 2048 --depth 4 --nodes 8000 --threads 8 \
  --seed 1 --output runs/hce.jsonl

# Train from random parameters; --resume accepts this project's own .pt files.
uv run --frozen --extra cu128 -m trainer.train \
  --data runs/hce.jsonl --output runs/candidate.nnue \
  --epochs 40 --seed 42 --device cuda --batch-size 4096 \
  --workers 4 --precision auto

# Match the fixed baseline using identical search settings for both engines.
./target/release/arena \
  --candidate runs/candidate.nnue --baseline hce \
  --pairs 256 --depth 4 --nodes 8000 --threads 8 \
  --seed 900000 --output runs/arena.json
```

`selfplay` and `arena` support rules 0/1/2. The trainer currently accepts only freestyle Gomoku (0), because the network has no rule feature and mixed-rule training would be ambiguous. Strength conclusions apply only to the rule used for training.

## Engine design and limits

- Square boards from 5 to 20 intersections per side; freestyle Gomoku, standard Gomoku with exact-five wins, and Renju forbidden moves. Renju uses recursive genuine-three checks, distinct-four grouping, and exact-five priority. Special swap-opening negotiation is outside the current scope.
- Resumable explicit-stack Alpha-Beta, iterative deepening, transposition tables, pattern ordering, killer/history ordering, and continuous-four/forced-defense quiescence search. Candidates are restricted to within two intersections of existing stones, and non-forcing branches have a width limit. This is selective search, not an exhaustive winning-proof solver.
- Six-cell directional patterns use two-bit symbols for empty, black, white, and boundary. Reversed patterns are canonicalized into a 4096-index space. A shared 32-dimensional embedding and two color accumulators feed clipped ReLU, an antisymmetric position value, and a tempo term. Moves and undo update incrementally. Loading weights switches static evaluation to NNUE; tactical ordering continues to use HCE.
- `.nnue` uses this project's `NOLOS001` format, with architecture metadata and FNV-1a checksum, approximately 513 KiB. **Rapfi and Stockfish weights are incompatible.**
- One search thread. Native input runs on a separate thread; the browser Worker handles commands between short work slices. `YXSTOP` returns the best move from a completed iteration, and the search copy does not modify the authoritative board.

See [protocol support](docs/protocol.md), [network format](docs/network.md), and [the initial experiment](docs/experiment.md).

## Validation

```bash
cargo test
cargo build --release --bins
scripts/build-web.sh
python3 scripts/check_protocol.py
node scripts/check_wasm.mjs web/nolos_nnue.wasm artifacts/generation-0.nnue

# Compare PyTorch, native Rust, and WASM on generated positions.
uv run --frozen --extra cpu -m scripts.check_network \
  --data runs/hce.jsonl --weights runs/candidate.nnue --samples 100
```

Numerical checks require the `.pt` checkpoint corresponding to the `.nnue` file. Rebuild the original sample data using the [experiment record](docs/experiment.md). GitHub Actions includes a small end-to-end check.

## Static deployment

Any static hosting service can serve `web/`. The GitHub Pages workflow `pages.yml` uses manual dispatch. Set Settings → Pages → Source to GitHub Actions, then run “Deploy static WASM website” on `seed` from Actions. GitHub only exposes manually dispatched workflows when they exist on the repository's default branch: if `master` remains the default and lacks this workflow, first make the workflow available there or deliberately change the default branch. This project does not change `master`, push, or deploy automatically.

## Rapfi and KataGomo

“Rapfi uses KataGomo knowledge” is accurate; “KataGomo parameters initialize its NNUE” is not an accurate description. [Rapfi paper §§4.1–4.2](https://arxiv.org/html/2503.13178v1#S4) describes supervised training on approximately 30.8 million KataGomo-generated positions with value and policy labels, together with a ResNet distillation teacher trained on the same dataset. This differs from directly inheriting parameters. NolosNNUE instead starts the training loop with its own HCE search.

## License

MIT. Engine, trainer, and website code were implemented for this project. Protocol and algorithm references informed the implementation; no Yixin-Board source is copied or committed.
