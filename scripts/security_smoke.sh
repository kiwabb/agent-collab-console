#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$ROOT_DIR/backend/.venv314/bin/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv314/bin/python"
elif [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/bin/python"
else
  PYTHON="python3"
fi

cd "$ROOT_DIR"
"$PYTHON" -m pytest -q \
  backend/tests/test_local_auth.py \
  backend/tests/test_project_command.py \
  backend/tests/test_qa_workflow.py \
  backend/tests/test_env_crypto.py \
  backend/tests/test_env_materializer.py \
  backend/tests/test_conductor_main_loop.py::test_finalize_task_tool_accepts_implementation_with_passed_execution_evidence \
  backend/tests/test_conductor_main_loop.py::test_finalize_task_tool_rejects_role_and_status_without_execution_evidence \
  backend/tests/test_conductor_main_loop.py::test_finalize_task_tool_requires_confirmed_acceptance_criteria

(
  cd "$ROOT_DIR/frontend"
  node --import tsx --test tests/localAuthBoundary.test.ts
)

reserve_loopback_port() {
  "$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

wait_for_url() {
  local url="$1"
  local host="$2"
  local pid="$3"
  local attempt

  for attempt in {1..80}; do
    if curl --fail --silent --show-error --header "Host: $host" "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    sleep 0.25
  done
  return 1
}

assert_loopback_listener() {
  local port="$1"
  local service="$2"
  local listeners

  listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ "$listeners" != *"127.0.0.1:$port (LISTEN)"* ]]; then
    echo "$service did not bind to IPv4 loopback on port $port" >&2
    return 1
  fi
  if [[ "$listeners" == *"*:$port (LISTEN)"* ]]; then
    echo "$service exposed a wildcard listener on port $port" >&2
    return 1
  fi
}

RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-collab-security-smoke.XXXXXX")"
BACKEND_PID=""
FRONTEND_PID=""

cleanup_runtime_smoke() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  rm -f \
    "$RUNTIME_DIR/backend.log" \
    "$RUNTIME_DIR/frontend.log" \
    "$RUNTIME_DIR/response-body" \
    "$RUNTIME_DIR/response-headers"
  rmdir "$RUNTIME_DIR" 2>/dev/null || true
}

trap cleanup_runtime_smoke EXIT
trap 'exit 130' INT TERM

BACKEND_PORT="$(reserve_loopback_port)"
FRONTEND_PORT="$(reserve_loopback_port)"
while [[ "$FRONTEND_PORT" == "$BACKEND_PORT" ]]; do
  FRONTEND_PORT="$(reserve_loopback_port)"
done

SMOKE_TOKEN="security-smoke-token_000000000000000000000000"
FRONTEND_ORIGIN="http://127.0.0.1:$FRONTEND_PORT"

(
  cd "$ROOT_DIR/backend"
  exec env \
    CONSOLE_AUTH_TOKEN="$SMOKE_TOKEN" \
    CONSOLE_ALLOWED_HOSTS="localhost,127.0.0.1,::1" \
    CONSOLE_ALLOWED_ORIGINS="$FRONTEND_ORIGIN" \
    REAL_CLI="false" \
    USE_SQLITE="false" \
    "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$RUNTIME_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

if ! wait_for_url \
  "http://127.0.0.1:$BACKEND_PORT/api/health" \
  "127.0.0.1:$BACKEND_PORT" \
  "$BACKEND_PID"; then
  echo "temporary backend failed to start" >&2
  tail -n 80 "$RUNTIME_DIR/backend.log" >&2
  exit 1
fi

(
  cd "$ROOT_DIR/frontend"
  exec env \
    BACKEND_API_BASE="http://127.0.0.1:$BACKEND_PORT" \
    CONSOLE_AUTH_TOKEN="$SMOKE_TOKEN" \
    NEXT_TELEMETRY_DISABLED="1" \
    node ./node_modules/next/dist/bin/next dev \
      --hostname 127.0.0.1 \
      --port "$FRONTEND_PORT"
) >"$RUNTIME_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

if ! wait_for_url \
  "http://127.0.0.1:$FRONTEND_PORT/console-auth" \
  "127.0.0.1:$FRONTEND_PORT" \
  "$FRONTEND_PID"; then
  echo "temporary frontend failed to start" >&2
  tail -n 80 "$RUNTIME_DIR/frontend.log" >&2
  exit 1
fi

assert_loopback_listener "$BACKEND_PORT" "backend"
assert_loopback_listener "$FRONTEND_PORT" "frontend"

RESPONSE_BODY="$RUNTIME_DIR/response-body"
RESPONSE_HEADERS="$RUNTIME_DIR/response-headers"

BAD_HOST_STATUS="$(
  curl --silent --show-error \
    --dump-header "$RESPONSE_HEADERS" \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: console.attacker.test" \
    "http://127.0.0.1:$FRONTEND_PORT/api/browser-smoke"
)"
if [[ "$BAD_HOST_STATUS" != "403" ]] || [[ "$(<"$RESPONSE_BODY")" != *'"detail":"host_not_allowed"'* ]]; then
  echo "frontend bad-Host request did not fail closed" >&2
  exit 1
fi
if awk 'tolower($0) ~ /^set-cookie:/ { found = 1 } END { exit found ? 0 : 1 }' "$RESPONSE_HEADERS"; then
  echo "frontend bad-Host response unexpectedly set an auth cookie" >&2
  exit 1
fi

COOKIE_STATUS="$(
  curl --silent --show-error \
    --dump-header "$RESPONSE_HEADERS" \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: 127.0.0.1:$FRONTEND_PORT" \
    "http://127.0.0.1:$FRONTEND_PORT/console-auth"
)"
if [[ "$COOKIE_STATUS" != "200" ]] || [[ "$(<"$RESPONSE_BODY")" != *'"ready":true'* ]]; then
  echo "valid loopback auth bootstrap did not succeed" >&2
  exit 1
fi
if ! awk '
  tolower($0) ~ /^set-cookie:/ &&
  tolower($0) ~ /httponly/ &&
  tolower($0) ~ /samesite=strict/ { found = 1 }
  END { exit found ? 0 : 1 }
' "$RESPONSE_HEADERS"; then
  echo "valid loopback auth bootstrap did not set a strict HttpOnly cookie" >&2
  while IFS= read -r header_line; do
    echo "${header_line//$SMOKE_TOKEN/[redacted]}" >&2
  done <"$RESPONSE_HEADERS"
  exit 1
fi

VALID_STATUS="$(
  curl --silent --show-error \
    --dump-header "$RESPONSE_HEADERS" \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: 127.0.0.1:$FRONTEND_PORT" \
    --header "Origin: $FRONTEND_ORIGIN" \
    "http://127.0.0.1:$FRONTEND_PORT/api/browser-smoke"
)"
if [[ "$VALID_STATUS" != "200" ]] || [[ "$(<"$RESPONSE_BODY")" != *'"ok":true'* ]]; then
  echo "valid loopback rewrite did not reach the authenticated backend" >&2
  exit 1
fi

BAD_ORIGIN_STATUS="$(
  curl --silent --show-error \
    --dump-header "$RESPONSE_HEADERS" \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: 127.0.0.1:$FRONTEND_PORT" \
    --header "Origin: https://console.attacker.test" \
    "http://127.0.0.1:$FRONTEND_PORT/api/browser-smoke"
)"
if [[ "$BAD_ORIGIN_STATUS" != "403" ]] || [[ "$(<"$RESPONSE_BODY")" != *'"detail":"origin_not_allowed"'* ]]; then
  echo "rewritten request with a bad Origin did not fail closed" >&2
  exit 1
fi

echo "Runtime local-auth smoke passed on loopback-only temporary listeners."
