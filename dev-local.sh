#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_VENV_PYTHON=""
BACKEND_UVICORN_CMD=()
export CODEX_SOURCE_ROOT="$ROOT_DIR"
export CODEX_WORKSPACE_ROOT="${CODEX_WORKSPACE_ROOT:-/tmp/agent-collab-console-workspaces}"

mkdir -p "$CODEX_WORKSPACE_ROOT"

if [[ -x "$BACKEND_DIR/.venv314/bin/python" ]]; then
  BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv314/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

check_port() {
  local port=$1
  local service=$2
  if lsof -i :"$port" >/dev/null 2>&1; then
    echo "Error: port $port is already in use by another process."
    if [[ "$port" == "8000" ]]; then
      echo "If a non-backend service is running on 8000, the frontend (port 5173) will proxy /api to that wrong service,"
      echo "causing the page to show briefly then go blank or show errors."
    fi
    echo "Stop the conflicting service or free port $port, then re-run this script."
    echo "To free port $port, you can run:"
    echo "  lsof -ti:$port | xargs kill -9"
    exit 1
  fi
}

if ! command -v codex >/dev/null 2>&1; then
  echo "Error: 'codex' command not found in your local shell."
  echo "Please verify 'which codex' works before starting the local workspace."
  exit 1
fi

if [[ -n "$BACKEND_VENV_PYTHON" ]]; then
  BACKEND_UVICORN_CMD=("$BACKEND_VENV_PYTHON" -m uvicorn)
elif command -v uvicorn >/dev/null 2>&1; then
  BACKEND_UVICORN_CMD=(uvicorn)
else
  echo "Error: backend runtime not found."
  echo "Create a virtual environment first or install uvicorn globally."
  echo "Recommended:"
  echo "  cd \"$BACKEND_DIR\" && python3.14 -m venv .venv314 && .venv314/bin/pip install -r requirements.txt httpx"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: 'npm' command not found."
  echo "Install Node.js and frontend dependencies first."
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Error: frontend dependencies are missing."
  echo "Run:"
  echo "  cd \"$FRONTEND_DIR\" && npm install"
  exit 1
fi

check_port 8000 "backend"
check_port 4000 "frontend"

echo "Starting backend on http://localhost:8000"
echo "Codex workspace root: $CODEX_WORKSPACE_ROOT"
if [[ -n "$BACKEND_VENV_PYTHON" ]]; then
  echo "Using backend virtualenv: $BACKEND_VENV_PYTHON"
else
  echo "Using global uvicorn from PATH"
fi
(
  cd "$BACKEND_DIR"
  exec "${BACKEND_UVICORN_CMD[@]}" app.main:app --reload --port 8000
) &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:4000"
(
  cd "$FRONTEND_DIR"
  exec npm run dev
) &
FRONTEND_PID=$!

echo
echo "Codex Terminal Workspace is starting."
echo "Frontend: http://localhost:4000"
echo "Backend:  http://localhost:8000"
echo "Press Ctrl+C to stop both services."
echo

wait "$BACKEND_PID" "$FRONTEND_PID"
