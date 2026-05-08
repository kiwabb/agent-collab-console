import subprocess
import json
import time
import os
import threading
import sys

# Ensure we have a decent PATH
env = os.environ.copy()
paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin", os.path.expanduser("~/.npm-global/bin")]
env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")

cmd = ["/Users/zhoujiaangyao/.npm-global/bin/codex", "app-server"]
print(f"Spawning: {' '.join(cmd)}")
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

responses = {}
notifications = []
shutdown = False

def reader():
    while not shutdown:
        line = proc.stdout.readline().decode()
        if not line: break
        try:
            msg = json.loads(line)
            if "id" in msg:
                responses[msg["id"]] = msg
            else:
                notifications.append(msg)
                print(f"NOTIF: {msg.get('method')} {str(msg.get('params', {}))[:100]}")
        except:
            print(f"STDOUT: {line.strip()}")

def stderr_reader():
    while not shutdown:
        line = proc.stderr.readline().decode()
        if not line: break
        print(f"STDERR: {line.strip()}")

threading.Thread(target=reader, daemon=True).start()
threading.Thread(target=stderr_reader, daemon=True).start()

def send_req(id, method, params=None):
    payload = {"jsonrpc": "2.0", "method": method}
    if id is not None: payload["id"] = id
    if params is not None: payload["params"] = params
    msg = json.dumps(payload)
    print(f"REQ: {method} (id={id})")
    proc.stdin.write(msg.encode() + b"\n")
    proc.stdin.flush()

def wait_for_resp(id, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        if id in responses:
            return responses[id]
        time.sleep(0.1)
    return None

# Handshake
send_req(1, "initialize", {"clientInfo": {"name": "test", "version": "1.0"}, "capabilities": {}})
print("Init Resp:", wait_for_resp(1))

send_req(None, "initialized", {})

send_req(2, "thread/start", {})
thread_resp = wait_for_resp(2)
print("Thread Start Resp:", thread_resp)

if thread_resp and "result" in thread_resp:
    res = thread_resp["result"]
    # Try both ways
    thread_id = None
    if "thread_id" in res: thread_id = res["thread_id"]
    elif "thread" in res and "id" in res["thread"]: thread_id = res["thread"]["id"]

    if thread_id:
        print(f"Thread ID detected: {thread_id}")
        send_req(3, "turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "say 'pong' and nothing else", "text_elements": []}]
        })
        print("Turn Start Resp:", wait_for_resp(3))

        print("Waiting for completion...")
        for _ in range(100):
            for n in notifications:
                if n.get("method") in ["turn.completed", "turn/completed"]:
                    print(f"SUCCESS: Found completion notif: {n.get('method')}")
                    shutdown = True
                    break
            if shutdown: break
            time.sleep(0.5)

shutdown = True
proc.terminate()
