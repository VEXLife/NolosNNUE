#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" -m scripts.search_gen9 \
  --output "${RUN_DIR:-runs/init-compare-001}" \
  --threads "${THREADS:-6}" --device "${TRAIN_DEVICE:-cuda}" \
  --reuse-data artifacts/search-gen9-002-training.jsonl \
  --compare-initialization --epochs 40 "$@"
