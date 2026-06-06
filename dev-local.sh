#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
FRONTEND_SWC_CACHE_DIR="$FRONTEND_DIR/.next/cache/next-swc"
FRONTEND_NODE_BIN=""
BACKEND_VENV_PYTHON=""
BACKEND_UVICORN_CMD=()
BACKEND_LOG_PATH="${BACKEND_LOG_PATH:-/tmp/agent-collab-backend.log}"
export CODEX_SOURCE_ROOT="$ROOT_DIR"
export CODEX_WORKSPACE_ROOT="${CODEX_WORKSPACE_ROOT:-/tmp/agent-collab-console-workspaces}"
# Real-CLI mode is the production default — Engineer must actually patch the
# worktree, QA must actually run tests. Override with `REAL_CLI=false ./dev-local.sh`
# for offline / demo mode where you want mock outputs.
export REAL_CLI="${REAL_CLI:-true}"
# Same idea for the Codex process manager. Disable only for fast unit tests.
export CODEX_LAUNCH_ENABLED="${CODEX_LAUNCH_ENABLED:-true}"
# Auto-reload restarts the uvicorn worker on every backend code change, which
# kills in-flight conductor subagent subprocesses (they get marked failed on
# boot). Keep it on for fast local dev (default), set DEV_RELOAD=false for a
# stable long-running instance (e.g. under tmux) where you don't want code
# edits to interrupt running issues.
DEV_RELOAD="${DEV_RELOAD:-true}"

# macOS 26 + Homebrew python@3.14: pyexpat.so 链接的是 /usr/lib/libexpat.1.dylib，
# 但 Tahoe dyld cache 里的版本旧于 expat 2.7，缺 _XML_SetAllocTrackerActivationThreshold
# 等新符号，pip / 任何 import xml.parsers.expat 的代码都会崩。指向 brew expat 即可。
if [[ -d "/opt/homebrew/opt/expat/lib" ]]; then
  export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

mkdir -p "$CODEX_WORKSPACE_ROOT"
mkdir -p "$FRONTEND_SWC_CACHE_DIR"

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

free_port() {
  local port=$1
  local service=$2
  local pids
  pids="$(lsof -ti :"$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Port $port ($service) is in use by PID(s): $pids — killing to free it."
  kill $pids 2>/dev/null || true
  # Wait up to ~5s for graceful exit, then SIGKILL anything still alive.
  for _ in 1 2 3 4 5; do
    pids="$(lsof -ti :"$port" 2>/dev/null || true)"
    [[ -z "$pids" ]] && break
    sleep 1
  done
  if [[ -n "$pids" ]]; then
    echo "PID(s) $pids still holding port $port — sending SIGKILL."
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
  if lsof -i :"$port" >/dev/null 2>&1; then
    echo "Error: failed to free port $port. Inspect with: lsof -i :$port"
    exit 1
  fi
  echo "Port $port is free."
}

if ! command -v codex >/dev/null 2>&1; then
  echo "Error: 'codex' command not found in your local shell."
  echo "Please verify 'which codex' works before starting the local workspace."
  exit 1
fi

if [[ "$REAL_CLI" == "true" ]] && ! command -v claude >/dev/null 2>&1; then
  echo "Warning: REAL_CLI=true but 'claude' command not found in PATH."
  echo "Engineer/QA tasks routed to the Claude executor will fail. Either:"
  echo "  - Install Claude Code: https://docs.claude.com/claude-code"
  echo "  - Set CLAUDE_CMD to an alternative binary, or"
  echo "  - Re-run with REAL_CLI=false to use mock adapters."
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

if [[ -x /usr/local/bin/node ]]; then
  FRONTEND_NODE_BIN="/usr/local/bin/node"
elif command -v node >/dev/null 2>&1; then
  FRONTEND_NODE_BIN="$(command -v node)"
else
  echo "Error: 'node' command not found."
  echo "Install Node.js and frontend dependencies first."
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Error: frontend dependencies are missing."
  echo "Run:"
  echo "  cd \"$FRONTEND_DIR\" && npm install"
  exit 1
fi

free_port 9000 "backend"
free_port 4000 "frontend"

echo "Starting backend on http://localhost:9000"
echo "Backend log: $BACKEND_LOG_PATH"
echo "Codex workspace root: $CODEX_WORKSPACE_ROOT"
if [[ -n "$BACKEND_VENV_PYTHON" ]]; then
  echo "Using backend virtualenv: $BACKEND_VENV_PYTHON"
else
  echo "Using global uvicorn from PATH"
fi
(
  cd "$BACKEND_DIR"
  : > "$BACKEND_LOG_PATH"
  if [[ "$DEV_RELOAD" == "true" ]]; then
    "${BACKEND_UVICORN_CMD[@]}" app.main:app --reload --port 9000 2>&1 | tee "$BACKEND_LOG_PATH"
  else
    "${BACKEND_UVICORN_CMD[@]}" app.main:app --port 9000 2>&1 | tee "$BACKEND_LOG_PATH"
  fi
) &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:4000"
(
  cd "$FRONTEND_DIR"
  export NEXT_SWC_PATH="$FRONTEND_SWC_CACHE_DIR"
  exec env -u NODE_OPTIONS "$FRONTEND_NODE_BIN" ./node_modules/next/dist/bin/next dev --port 4000
) &
FRONTEND_PID=$!

echo
echo "Codex Terminal Workspace is starting."
echo "Frontend: http://localhost:4000"
echo "Backend:  http://localhost:9000"
echo "Press Ctrl+C to stop both services."
echo

wait "$BACKEND_PID" "$FRONTEND_PID"
