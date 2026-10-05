#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
resume_args=()
if [[ "${RESUME:-0}" == 1 ]]; then resume_args+=(--resume-run); fi
exec "${PYTHON:-python}" -m trainer.bootstrap \
  --run-dir "${RUN_DIR:-runs/hce-evolution-001}" \
  --generations "${GENERATIONS:-30}" --games "${GAMES:-4096}" \
  --epochs "${EPOCHS:-100}" --threads "${THREADS:-6}" \
  --selfplay-nodes "${SELFPLAY_NODES:-50000}" --selfplay-depth 64 \
  --nodes "${ARENA_NODES:-50000}" --depth 64 --branch 16 --size 15 \
  --pairs "${PAIRS:-128}" --confirm-pairs 0 --promotion-policy score --promotion-score .52 \
  --arena-time-ms 0 --exploration "${EXPLORATION:-.6}" \
  --architecture legacy --policy-weight 0 --outcome-weight 0 \
  --train-resume candidate --train-revive-flat-units \
  --thin-mates --replay-generations 4 --train-lr .003 \
  --data-score-limit 1000 --train-label-smoothing .025 --train-early-stop-patience 10 --train-early-stop-min-delta .0001 \
  --train-device "${TRAIN_DEVICE:-cuda}" --train-batch-size 1024 \
  --train-workers 0 --train-precision fp32 --train-deterministic \
  --seed 1030562001 "${resume_args[@]}" "$@"
