#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONPATH="$ROOT_DIR" uv run --directory "$ROOT_DIR" --python 3.11 --extra dev pytest -v "$ROOT_DIR/tests"
npm --prefix "$ROOT_DIR/packages/renderer" test
npm --prefix "$ROOT_DIR/packages/renderer" run build
npm --prefix "$ROOT_DIR/apps/web" test
npm --prefix "$ROOT_DIR/apps/web" run build
