#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cargo build --release --lib --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/nolos_nnue.wasm web/nolos_nnue.wasm
if [ "${1:-}" = "--single" ]; then
  python3 scripts/pack_single.py ${2:+--model "$2"}
  printf 'Deploy dist/nolos.html (rename to index.html for GitHub Pages)\n'
fi
printf 'Static site ready in web/\nPreview: python3 -m http.server 8000 --directory web\n'
