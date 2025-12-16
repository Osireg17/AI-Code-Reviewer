#!/bin/bash
set -euo pipefail

cleanup() {
  echo "Received shutdown signal, stopping services..."
  if kill -0 "$WORKER_PID" 2>/dev/null; then
    kill "$WORKER_PID"
  fi
  if kill -0 "$WEB_PID" 2>/dev/null; then
    kill "$WEB_PID"
  fi
  wait "$WORKER_PID" 2>/dev/null || true
  wait "$WEB_PID" 2>/dev/null || true
  exit 0
}

python worker.py &
WORKER_PID=$!

uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
WEB_PID=$!

trap cleanup SIGINT SIGTERM

wait "$WORKER_PID" "$WEB_PID"
