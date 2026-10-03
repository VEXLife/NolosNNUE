#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" -m scripts.search_gen9 \
  --output "${RUN_DIR:-runs/search-gen9-001}" \
  --threads "${THREADS:-6}" --device "${TRAIN_DEVICE:-cuda}" "$@"
