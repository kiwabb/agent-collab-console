#!/usr/bin/env python3
"""
诊断脚本：检查任务执行状态问题

使用方法：
python debug_task_status.py <task_id>
"""
import sys
import sqlite3
import json
from pathlib import Path

def check_task_status(task_id: str, workspace_path: str = ".task-workspaces/073c253f-e744-42db-8548-54385aec141e"):
    """检查任务状态和相关日志"""
    db_path = Path(workspace_path) / "codex.db"
    
    if not db_path.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 检查任务基本信息
    print("=" * 60)
    print("📋 任务基本信息")
    print("=" * 60)
    cursor.execute("SELECT * FROM codex_tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    
    if not task:
        print(f"❌ 找不到任务 ID: {task_id}")
        conn.close()
        return
    
    for key in task.keys():
        value = task[key]
        if key in ('prompt', 'result') and value and len(str(value)) > 100:
            value = str(value)[:100] + "..."
        print(f"  {key}: {value}")
    
    # 2. 检查日志事件
    print("\n" + "=" * 60)
    print("📝 最近的日志事件 (最后20条)")
    print("=" * 60)
    cursor.execute("""
        SELECT id, stream, content, created_at 
        FROM log_events 
        WHERE task_id = ? 
        ORDER BY created_at DESC 
        LIMIT 20
    """, (task_id,))
    
    logs = cursor.fetchall()
    if not logs:
        print("  ⚠️  没有找到日志事件")
    else:
        for log in reversed(logs):
            content = log['content']
            if len(content) > 150:
                content = content[:150] + "..."
            print(f"  [{log['stream']}] {content}")
    
    # 3. 检查通知事件
    print("\n" + "=" * 60)
    print("🔔 通知事件")
    print("=" * 60)
    cursor.execute("""
        SELECT content 
        FROM log_events 
        WHERE task_id = ? AND stream = 'notification'
        ORDER BY created_at
    """, (task_id,))
    
    notifications = cursor.fetchall()
    if not notifications:
        print("  ⚠️  没有找到通知事件")
    else:
        for notif in notifications:
            try:
                data = json.loads(notif['content'])
                method = data.get('method', 'unknown')
                print(f"  • {method}")
                if method in ('turn.completed', 'turn/completed'):
                    print("    ✅ 找到完成通知!")
            except:
                print(f"  • {notif['content'][:100]}")
    
    # 4. 检查进程状态
    print("\n" + "=" * 60)
    print("⚙️  执行进程状态")
    print("=" * 60)
    cursor.execute("""
        SELECT * FROM execution_processes 
        WHERE task_id = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    """, (task_id,))
    
    process = cursor.fetchone()
    if not process:
        print("  ⚠️  没有找到执行进程记录")
    else:
        for key in process.keys():
            print(f"  {key}: {process[key]}")
    
    # 5. 诊断建议
    print("\n" + "=" * 60)
    print("💡 诊断建议")
    print("=" * 60)
    
    if task['status'] == 'responding':
        print("  ⚠️  任务状态为 'responding'，说明:")
        print("     1. 后端已启动任务执行")
        print("     2. 但尚未收到完成通知")
        print()
        
        has_turn_completed = False
        for notif in notifications:
            try:
                data = json.loads(notif['content'])
                if data.get('method') in ('turn.completed', 'turn/completed'):
                    has_turn_completed = True
                    break
            except:
                pass
        
        if has_turn_completed:
            print("  ✅ 数据库中有 turn.completed 通知")
            print("     → 问题：通知处理逻辑可能有bug")
            print("     → 检查 _mark_task_done 方法是否被正确调用")
        else:
            print("  ❌ 数据库中没有 turn.completed 通知")
            print("     → 问题：codex进程可能:")
            print("        • 仍在运行中")
            print("        • 已崩溃但未发送完成通知")
            print("        • 通知未被正确捕获和记录")
            print()
            print("  🔍 建议检查:")
            print("     1. 后端日志 (stderr输出)")
            print("     2. codex进程是否还在运行: ps aux | grep codex")
            print("     3. 检查 _make_app_server_notification_callback 是否正常工作")
    
    elif task['status'] == 'done':
        print("  ✅ 任务已完成")
    elif task['status'] == 'failed':
        print("  ❌ 任务执行失败")
    else:
        print(f"  ℹ️  任务状态: {task['status']}")
    
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python debug_task_status.py <task_id>")
        print("\n提示: 你可以从前端URL或数据库中获取task_id")
        sys.exit(1)
    
    task_id = sys.argv[1]
    workspace = sys.argv[2] if len(sys.argv) > 2 else ".task-workspaces/073c253f-e744-42db-8548-54385aec141e"
    
    check_task_status(task_id, workspace)
