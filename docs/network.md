# NOLOS001 network format

English | [简体中文](network.zh-CN.md)

Rust inference is implemented in `src/network.rs`; the PyTorch model is in `trainer/model.py`. Unsupported architectures, non-finite parameters, bad checksums, and incorrect lengths are rejected without replacing the current network.

## Features

The board is decomposed into horizontal, vertical, and both diagonal lines. Whole lines shorter than five cells are ignored. For a line of length L, six-cell window start positions range from -5 through L-1. Out-of-bounds cells are encoded as 3, empty as 0, black as 1, and white as 2. The first cell occupies the lowest two bits.

Each window is canonicalized to the smaller of its forward and reversed encodings, then accumulated in `counts[4096]`. For the white perspective, symbols 1 and 2 are exchanged and the result canonicalized again. Embeddings are shared across directions, making features invariant under all eight board rotations/reflections.

```text
black_acc = bias + sum(count[id] × embedding[id]) / 32
white_acc = bias + sum(count[id] × embedding[invert(id)]) / 32
black_logit = sum((clip(black_acc,0,1) - clip(white_acc,0,1)) × head)
side_logit = (black_to_play ? black_logit : -black_logit) + tempo
evaluation = round(side_logit × 600), clamped to [-12000,12000]
```

A move updates only windows containing its cell, feature counts, accumulators, and HCE pattern scores. Undo reverses those updates. Accumulators are rebuilt at the start of a search and after weight loading to control floating-point accumulation error. Cross-backend checks allow an evaluation difference of at most one point.

## Binary layout

All integers and floats are little-endian; f32 uses IEEE-754. Total file size is **524576 bytes**.

| Offset | Length | Meaning |
| --- | --- | --- |
| 0 | 8 | ASCII `NOLOS001` |
| 8 | 4 | u32 feature count: 4096 |
| 12 | 4 | u32 hidden dimension: 32 |
| 16 | 4 | f32 feature normalizer: 32.0 |
| 20 | 4 | f32 score multiplier: 600.0 |
| 24 | 4 | u32 FNV-1a checksum of the payload |
| 28 | 524288 | f32 embedding[4096][32], feature-major |
| 524316 | 128 | f32 bias[32] |
| 524444 | 128 | f32 head[32] |
| 524572 | 4 | f32 tempo |

FNV-1a starts at 2166136261 and processes each byte as `(hash XOR byte) × 16777619`, retaining the low 32 bits. Training logs also record SHA-256 to identify the entire file. FNV is an integrity check, not a security signature.

`.pt` contains a PyTorch state_dict and is read with `weights_only=True`. It supports continued training and numerical verification; the browser and Rust engine do not read `.pt` files.

## Targets and evaluation

The training output is a logit of the side-to-move win probability. The default target is `0.7 × sigmoid(search_score/600) + 0.3 × game_outcome`; truncated games use only the search label. Terminal positions and near-winning search scores are excluded. Validation is grouped by whole games, and the checkpoint with the best validation loss is exported. Promotion still requires independent paired matches.
