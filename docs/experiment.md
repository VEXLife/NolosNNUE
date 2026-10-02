# Initial bootstrap experiment

English | [简体中文](experiment.zh-CN.md)

## Question

Can self-written HCE search and self-play train an NNUE without external data or parameters and improve it across generations? This project implements a runnable pipeline. The small initial experiment did not demonstrate stronger play and does not establish that scaling alone will succeed.

## Executed experiment

Run locally on CPU on 2026-10-02 using the final corrected generator, which prevents exploration from bypassing forced defense and fixes validation cohorts across generations. Self-play and arena used 15×15 freestyle Gomoku, depth 3, at most 1500 nodes per move, a non-root branch limit of 12, and six plies of continuous-four quiescence search. This was not a GPU experiment. Training used the original CPU sparse-batch implementation; the subsequent GPU-oriented batching changes have not been benchmarked on NVIDIA hardware.

```bash
cargo build --release --bins
./target/release/selfplay --games 512 --nodes 1500 --depth 3 \
  --threads 4 --output artifacts/hce-selfplay.jsonl
uv run --frozen --extra cpu -m trainer.train \
  --data artifacts/hce-selfplay.jsonl \
  --output artifacts/generation-0.nnue --epochs 60 --threads 2 --seed 42
./target/release/arena --candidate artifacts/generation-0.nnue --baseline hce \
  --pairs 128 --nodes 1500 --depth 3 --threads 4 \
  --output artifacts/generation-0.arena.json
```

The commands above select today's CPU dependency extra; the stored results were produced before the GPU batching update. Self-play used its default seed 1, exploration probability 0.1, and HCE teacher. It generated 512 games and 8597 nonterminal training positions, with no truncated games. Of those games, 501 produced usable non-winning-score positions; the remainder contained only filtered tactical positions. Whole-game splitting yielded 7196 training positions and 1401 validation positions, with 75 validation games.

## Results

| Metric | Measurement |
| --- | --- |
| Initial random-network validation cross-entropy | 0.6931641039 |
| Best validation cross-entropy | 0.6616090425 |
| Exported checkpoint | Epoch 1, rather than the final epoch |
| Matches against HCE | 128 opening pairs, 256 games |
| Wins / losses / draws | 108 / 146 / 2 |
| Truncated games | 0 |
| Score | 42.5781% |
| Approximate 95% CI using opening pairs | [37.7364%, 47.4199%] |
| Promotion | **Rejected; HCE remains the teacher** |

Full training record: [`generation-0.training.json`](../artifacts/generation-0.training.json). Paired results: [`generation-0.arena.json`](../artifacts/generation-0.arena.json). Weights: [`generation-0.nnue`](../artifacts/generation-0.nnue).

The interval uses sample variance of opening-pair scores and a normal approximation; small samples do not qualify for promotion. It is an experimental diagnostic, not an official league rating. Relative Elo comes only from these matches and cannot be compared to Gomocup rankings.

## Larger experiments

The first run contained roughly eight thousand positions, whereas the Rapfi paper used approximately 30.8 million positions from a strong teacher. Data volume, search-label quality, architecture, and candidate pruning may all affect results. More data has not been established as the sole missing ingredient.

Start with the README's small pipeline to verify your environment, then run the large configuration. Watch:

- Match score, rather than training loss alone; retain the fixed HCE control.
- Paired, color-swapped matches against both the preceding champion and HCE in every generation.
- Teacher search depth, exploration, and opening coverage before simply increasing game count; avoid repeatedly learning a narrow set of similar positions.
- Multiple seeds and rejected generations. Persistent failure to promote calls for inspecting feature expressiveness and candidate pruning rather than endlessly increasing compute.

Raw `.jsonl` and `.pt` files remain local and are excluded from Git. The generator determines openings and exploration from per-game seeds. Under fixed node budgets without time truncation, results can be regenerated; multithreaded output order can differ, so file-level SHA-256 may differ. The trainer sorts input so game grouping and sample ordering are reproducible. Updated training kernels or hardware may still produce different floating-point optimization results from the historical checkpoint.

## Completed validation

- Rust unit/integration tests: incremental patterns, hashing and undo, all eight board symmetries, winning rules, genuine/false threes, double fours, exact-five priority, forced moves, protocol transactions, and interruption.
- Real native process: CRLF, silent synchronization, search interruption, single replies, forbidden moves, and termination.
- Real WASM: shared protocol, ABI, weight loading, corrupted-file rejection, and interruption.
- PyTorch/native Rust/WASM numerical agreement: 100 generated positions, at most one point of floating-point difference.
- Browser: both human colors, noncommitting analysis, stop, undo, local/URL weights, retention after invalid weights, forbidden moves, game import/export, and mobile layout.
