#!/usr/bin/env python3
"""
Test script to verify the complete message flow:
1. Create a task
2. Run the task
3. Verify assistant message is saved to database
4. Verify message is broadcast via WebSocket
"""
import asyncio
import json
import sqlite3
import sys
import time
import websockets
import requests

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

def create_session():
    """Create a new session."""
    response = requests.post(
        f"{BASE_URL}/api/codex/sessions",
        json={"title": "Test Session", "cwd": ""}
    )
    response.raise_for_status()
    return response.json()

def create_task(session_id, title="Test Task", prompt="ping"):
    """Create a new task."""
    response = requests.post(
        f"{BASE_URL}/api/codex/tasks",
        json={
            "session_id": session_id,
            "title": title,
            "prompt": prompt,
            "executor": "codex"
        }
    )
    response.raise_for_status()
    return response.json()

def run_task(task_id):
    """Run a task."""
    response = requests.post(f"{BASE_URL}/api/codex/tasks/{task_id}/run")
    response.raise_for_status()
    return response.json()

def get_task_messages(task_id):
    """Get messages for a task from database."""
    conn = sqlite3.connect("backend/console.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, task_id, role, content, created_at FROM codex_task_messages WHERE task_id = ? ORDER BY created_at",
        (task_id,)
    )
    messages = cursor.fetchall()
    conn.close()
    return messages

async def listen_websocket(session_id, duration=15):
    """Listen to WebSocket for updates."""
    uri = f"{WS_URL}/api/sessions/{session_id}/execution_processes/ws"
    messages_received = []
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ WebSocket connected to {uri}")
            
            # Set a timeout for receiving messages
            start_time = time.time()
            while time.time() - start_time < duration:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(message)
                    messages_received.append(data)
                    
                    if "JsonPatch" in data:
                        print(f"✓ Received JSON Patch with {len(data['JsonPatch'])} operations")
                        for patch in data['JsonPatch']:
                            if 'messages' in patch.get('path', ''):
                                print(f"  → Message patch: {patch['op']} {patch['path']}")
                    elif "Ready" in data:
                        print(f"✓ Received Ready signal")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"✗ Error receiving message: {e}")
                    break
    except Exception as e:
        print(f"✗ WebSocket connection failed: {e}")
    
    return messages_received

async def main():
    print("=" * 60)
    print("Testing Message Flow")
    print("=" * 60)
    
    # Step 1: Create session
    print("\n1. Creating session...")
    session = create_session()
    session_id = session["id"]
    print(f"✓ Session created: {session_id}")
    
    # Step 2: Create task
    print("\n2. Creating task...")
    task = create_task(session_id, title="Message Flow Test", prompt="ping")
    task_id = task["id"]
    print(f"✓ Task created: {task_id}")
    
    # Step 3: Start WebSocket listener
    print("\n3. Starting WebSocket listener...")
    ws_task = asyncio.create_task(listen_websocket(session_id, duration=15))
    await asyncio.sleep(1)  # Give WebSocket time to connect
    
    # Step 4: Run task
    print("\n4. Running task...")
    run_result = run_task(task_id)
    print(f"✓ Task run initiated: {run_result}")
    
    # Step 5: Wait for task to complete
    print("\n5. Waiting for task to complete (15 seconds)...")
    await asyncio.sleep(15)
    
    # Step 6: Check database for messages
    print("\n6. Checking database for messages...")
    messages = get_task_messages(task_id)
    print(f"✓ Found {len(messages)} messages in database:")
    for msg in messages:
        msg_id, task_id_db, role, content, created_at = msg
        print(f"  - {role}: {content[:50]}..." if len(content) > 50 else f"  - {role}: {content}")
    
    # Step 7: Check WebSocket messages
    print("\n7. Checking WebSocket messages...")
    ws_messages = await ws_task
    print(f"✓ Received {len(ws_messages)} WebSocket messages")
    
    # Count message patches
    message_patches = 0
    for ws_msg in ws_messages:
        if "JsonPatch" in ws_msg:
            for patch in ws_msg["JsonPatch"]:
                if 'messages' in patch.get('path', ''):
                    message_patches += 1
    
    print(f"✓ Found {message_patches} message-related patches")
    
    # Step 8: Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Database messages: {len(messages)}")
    print(f"WebSocket message patches: {message_patches}")
    
    if len(messages) > 0 and message_patches > 0:
        print("\n✓ SUCCESS: Messages are being saved and broadcast!")
    elif len(messages) > 0:
        print("\n⚠ PARTIAL: Messages saved to DB but not broadcast via WebSocket")
    else:
        print("\n✗ FAILURE: No messages found")
    
    return len(messages) > 0 and message_patches > 0

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
