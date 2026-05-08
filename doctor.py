import sys
import os
import json
import uuid
import asyncio
from datetime import datetime
import subprocess

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath("backend"))

from app.application.codex_process_manager import CodexProcessManager
from app.bootstrap import async_store, event_bus

# Use async_store as codex_store and log_store
codex_store = async_store
log_store = async_store

# Mock event bus to capture events
class MockEventBus:
    def __init__(self):
        self.events = []
    
    async def append(self, event):
        print(f"BUS EVENT: {event['type']} {event.get('method', '')}")
    
    async def queue_log_event(self, event):
        # print(f"LOG EVENT: {event.stream} {event.content[:50]}...")
        pass
        
    def subscribe(self): return None
    def unsubscribe(self, q): pass

# Replace real event_bus with mock for doctor
mock_bus = MockEventBus()

print(f"--- DOCTOR DIAGNOSTIC (ASYNC) ---")

async def test_direct_popen():
    print("Test 1: Direct Popen with same parameters as manager...")
    cmd = ["/usr/local/bin/codex", "app-server"]
    # Binary path resolution
    for common_path in ["~/.npm-global/bin/codex", "/usr/local/bin/codex", "/opt/homebrew/bin/codex"]:
        expanded = os.path.expanduser(common_path)
        if os.path.exists(expanded):
            cmd[0] = expanded
            break

    env = os.environ.copy()
    paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin", os.path.expanduser("~/.npm-global/bin")]
    env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")
    
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    print(f"Spawned pid {proc.pid}")
    
    # Handshake 1: initialize
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name":"doctor", "version":"1.0"}}}) + "\n"
    proc.stdin.write(req.encode())
    proc.stdin.flush()
    print("Sent initialize request.")
    
    # Read one line
    print("Waiting for response line...")
    line = proc.stdout.readline()
    print(f"Response: {line.decode()}")
    
    proc.terminate()
    print("Test 1 finished.\n")

async def test_manager():
    print("Test 2: Using CodexProcessManager (Async)...")
    mgr = CodexProcessManager(codex_store, log_store, event_bus=mock_bus)
    session_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    
    # Create session
    from app.domain.models import CodexSession
    session = CodexSession(id=session_id, title="Doctor Session", cwd=os.getcwd(), created_at=datetime.now(), last_active_at=datetime.now())
    await codex_store.save_codex_session(session)
    
    # Create a task
    from app.domain.models import CodexTask
    task = CodexTask(
        id=task_id,
        session_id=session_id,
        title="Doctor Task",
        prompt="ping",
        status="pending",
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    await codex_store.save_codex_task(task)

    print(f"Calling write_input_async for {session_id}...")
    
    async def tracker():
        for _ in range(10):
            await asyncio.sleep(1)
            entry = mgr._processes.get(task_id or session_id)
            if entry:
                alive = entry.alive
                print(f"  [Track] Proc alive={alive}")
                if not alive: break
            else:
                print(f"  [Track] No process entry yet...")
    
    tracker_task = asyncio.create_task(tracker())
    
    try:
        # We'll use a short prompt to trigger handshake
        # Using wait=True to see if it finishes
        result = await mgr.write_input_async(
            workspace_id=session_id,
            input_text="Hello, are you there?",
            task_id=task_id,
            executor="codex",
            wait=True
        )
        print(f"write_input_async RETURNED with: {result}")
    except Exception as e:
        print(f"write_input_async FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tracker_task.cancel()
        await mgr.terminate_all()

async def main():
    await test_direct_popen()
    await test_manager()
    print("--- DOCTOR END ---")

if __name__ == "__main__":
    asyncio.run(main())
