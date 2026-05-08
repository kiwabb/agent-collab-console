#!/usr/bin/env python3
"""
Happy-path verification script for Task 58/61.

Proves per-turn model: create workspace -> send input -> receive Codex output.

Usage:
    cd backend
    CODEX_LAUNCH_ENABLED=true python3 verify_happy_path.py

Requires:
    - codex binary available in PATH
    - Backend services NOT running (this script manages its own process lifecycle)

Note: Each turn takes ~20-30 seconds due to model loading.
"""
import os
import sys
import time
import subprocess
import requests

API_BASE = "http://localhost:8000/api"
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def wait_for_backend(timeout=15):
    """Wait for backend to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{API_BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.5)
    return False


def main():
    print("=" * 60)
    print("Task 58/61 Happy-Path Verification (per-turn model)")
    print("=" * 60)

    # Check codex is available
    if not os.path.exists("/opt/homebrew/bin/codex") and not os.popen("which codex").read().strip():
        print("ERROR: codex not found in PATH")
        sys.exit(1)

    # Start backend with CODEX_LAUNCH_ENABLED=true
    env = os.environ.copy()
    env["CODEX_LAUNCH_ENABLED"] = "true"
    env["SQLITE_DB_PATH"] = os.path.join(BACKEND_DIR, "tests", "test_console.db")

    print("\n[1] Starting backend with CODEX_LAUNCH_ENABLED=true ...")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        if not wait_for_backend():
            print("ERROR: Backend failed to start within 15s")
            sys.exit(1)
        print("    Backend started ✓")

        # Step 1: Create workspace (no auto-launch in per-turn model)
        print("\n[2] Creating Codex workspace (per-turn model, no auto-launch) ...")
        r = requests.post(
            f"{API_BASE}/codex/workspaces",
            json={"title": "verify-happy-path", "cwd": "/tmp"},
        )
        if r.status_code not in (200, 201):
            print(f"ERROR: Failed to create workspace: {r.status_code} {r.text}")
            sys.exit(1)
        workspace = r.json()
        workspace_id = workspace["id"]
        print(f"    Created workspace: {workspace_id}")
        print(f"    Status: {workspace['status']} (expected: idle)")

        # Step 2: Send input — triggers one-shot codex exec
        print("\n[3] Sending 'print hello world' to Codex ...")
        prompt = "print hello world"
        r = requests.post(
            f"{API_BASE}/codex/workspaces/{workspace_id}/input",
            json={"input": prompt + "\n"},
        )
        if r.status_code != 200:
            print(f"ERROR: Failed to send input: {r.status_code} {r.text}")
            sys.exit(1)
        print(f"    Input sent ✓")

        # Step 3: Poll for log events (wait for turn.completed or agent_message)
        print("\n[4] Waiting for Codex response (this takes ~2-5 min due to model loading) ...")
        max_wait = 360
        start = time.time()
        turn_completed = False
        agent_message_seen = False

        while time.time() - start < max_wait:
            time.sleep(2)
            r = requests.get(f"{API_BASE}/codex/workspaces/{workspace_id}/logs")
            if r.status_code == 200:
                logs = r.json()
                for log in logs:
                    content = log.get("content", "")
                    if isinstance(content, str):
                        if "turn.completed" in content:
                            turn_completed = True
                        if '"type":"item.completed"' in content and "agent_message" in content:
                            agent_message_seen = True
                elapsed = int(time.time() - start)
                print(f"    [{elapsed}s] {len(logs)} log events, turn_completed={turn_completed}, agent_message={agent_message_seen}")

                if turn_completed or agent_message_seen:
                    print("\n" + "=" * 60)
                    print("SUCCESS: Happy path verified!")
                    print("  - Workspace created (per-turn model)")
                    print("  - Input sent")
                    print(f"  - turn.completed={turn_completed}")
                    print(f"  - agent_message={agent_message_seen}")
                    print("=" * 60)
                    sys.exit(0)

        print(f"\nERROR: turn.completed not seen within {max_wait}s")
        r = requests.get(f"{API_BASE}/codex/workspaces/{workspace_id}/logs")
        if r.status_code == 200:
            logs = r.json()
            streams = set(log.get("stream") for log in logs)
            print(f"    Got {len(logs)} logs, streams={streams}")
            for log in logs:
                content = log.get("content", "")
                if isinstance(content, str) and len(content) < 200:
                    print(f"    [{log.get('stream')}] {content[:200]}")
                elif isinstance(content, str):
                    print(f"    [{log.get('stream')}] {content[:200]}...")
        sys.exit(1)

    finally:
        print("\n[5] Shutting down backend ...")
        backend_proc.terminate()
        try:
            backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_proc.kill()
        print("    Backend stopped ✓")


if __name__ == "__main__":
    main()
