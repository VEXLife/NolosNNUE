# Experiment artifacts

English | [简体中文](README.zh-CN.md)

- `generation-0.nnue`: candidate from the final corrected small experiment, **not a champion**. HCE self-play produced 8597 training positions from 512 games. In 256 evaluation games it won 108, lost 146, and drew 2, scoring 42.58%; it was not promoted.
- `generation-0.training.json`: validation grouping, epoch losses, and model SHA-256.
- `generation-0.arena.json`: 128 independently seeded opening-pair results and approximate interval.
- `generation-0.manifest.json`: generation parameters, source checksums, and validation record.

See [the experiment record](../docs/experiment.md) for commands. Raw JSONL and PyTorch `.pt` files remain local and are excluded by `.gitignore`. Use the sample for native/browser weight-loading checks; the website defaults to HCE, which outperformed this candidate.
