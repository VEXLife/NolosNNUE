#!/usr/bin/env bash
# Large spatial value/policy experiment: gen9 teacher, independent new learner.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" -m trainer.bootstrap \
  --run-dir "${RUN_DIR:-runs/spatial-cloud-001}" \
  --initial-weights artifacts/cloud-gen9.nnue \
  --architecture spatial --initial-candidate artifacts/spatial-seed.nnue \
  --train-resume candidate \
  --generations 30 --max-rejections 0 \
  --games 8192 --epochs 20 --replay-generations 3 \
  --selfplay-nodes 200000 --selfplay-depth 64 \
  --nodes 50000 --depth 64 --branch 16 \
  --pairs 512 --confirm-pairs 512 --promotion-score 0.52 \
  --threads "${THREADS:-$(nproc)}" --seed 820261200 \
  --train-device "${TRAIN_DEVICE:-cuda}" --train-batch-size 256 \
  --train-workers 2 --train-precision fp32 --train-lr 0.001 \
  --policy-weight 0.5 --outcome-weight 0.30 --exploration 0.15 "$@"
