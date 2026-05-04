#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

existing_pids="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)"

if [[ -n "$existing_pids" ]]; then
  printf '127.0.0.1:8000 已被占用，正在重启后端服务。\n'
  env kill $existing_pids 2>/dev/null || true
  sleep 1

  remaining_pids="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$remaining_pids" ]]; then
    env kill -9 $remaining_pids 2>/dev/null || true
    sleep 1
  fi
fi

PYTHONPATH="$ROOT_DIR" uv run --directory "$ROOT_DIR" --python 3.11 uvicorn agent.api.main:app --app-dir "$ROOT_DIR" --reload --host 127.0.0.1 --port 8000
