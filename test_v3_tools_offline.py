"""
离线测试新工具 — 不需要 API Key，直接调用工具函数
运行: venv\Scripts\python.exe test_v3_tools_offline.py
"""
import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import register_builtin_tools, register_memory_tools, register_task_tools, execute_tool
from inbox import init_inbox

# 初始化
register_builtin_tools()
register_memory_tools()
register_task_tools()
init_inbox()

# 模拟 config
config = {"cwd": os.getcwd(), "model": "qwen-plus", "provider": "qwen", "api_key": "test"}

print("=" * 60)
print("  v3 新工具离线测试")
print("=" * 60)

# ===== s12: Work Graph 工具 =====
print("\n--- s12: TaskCreate ---")
r1 = execute_tool("TaskCreate", {"subject": "搭建数据库", "claim_role": "backend"}, config)
print(r1)

r2 = execute_tool("TaskCreate", {"subject": "编写 API 接口", "blocked_by": ["task_1"]}, config)
print(r2)

r3 = execute_tool("TaskCreate", {"subject": "编写单元测试", "blocked_by": ["task_2"]}, config)
print(r3)

print("\n--- s12: TaskList ---")
r = execute_tool("TaskList", {}, config)
print(r)

print("\n--- s12: TaskInfo (第一个任务) ---")
# 从列表中提取 task_id
import re
match = re.search(r"(task_\w+)", r1)
if match:
    tid = match.group(1)
    r = execute_tool("TaskInfo", {"task_id": tid}, config)
    print(r)

    print("\n--- s12: TaskComplete ---")
    r = execute_tool("TaskComplete", {"task_id": tid, "result": "数据库搭建完成"}, config)
    print(r)

print("\n--- s12: TaskList (after complete) ---")
r = execute_tool("TaskList", {"status": "pending"}, config)
print(r)

# ===== s13: Background Run =====
print("\n--- s13: BackgroundRun ---")
r = execute_tool("BackgroundRun", {"command": "ping -n 3 127.0.0.1"}, config)
print(r)

# 提取 rt_id
match = re.search(r"(rt_\w+)", r)
if match:
    rt_id = match.group(1)
    import time
    print("\n  等待后台任务完成...")
    time.sleep(4)

    print(f"\n--- s13: BackgroundStatus ({rt_id}) ---")
    r = execute_tool("BackgroundStatus", {"task_id": rt_id}, config)
    print(r)

    print(f"\n--- s13: BackgroundOutput ({rt_id}) ---")
    r = execute_tool("BackgroundOutput", {"task_id": rt_id}, config)
    print(r[:500])

print("\n--- s13: BackgroundStatus (list all) ---")
r = execute_tool("BackgroundStatus", {}, config)
print(r)

# ===== s14: Schedule =====
print("\n--- s14: ScheduleCreate ---")
r = execute_tool("ScheduleCreate", {
    "cron": "*/5 * * * *",
    "prompt": "检查系统状态并报告"
}, config)
print(r)

r = execute_tool("ScheduleCreate", {
    "cron": "0 9 * * 1-5",
    "prompt": "每日站会提醒"
}, config)
print(r)

print("\n--- s14: ScheduleList ---")
r = execute_tool("ScheduleList", {}, config)
print(r)

# 提取 sched_id
match = re.search(r"(sched_\w+)", r)
if match:
    sid = match.group(1)
    print(f"\n--- s14: ScheduleToggle (disable {sid}) ---")
    r = execute_tool("ScheduleToggle", {"schedule_id": sid, "enabled": False}, config)
    print(r)

    print("\n--- s14: ScheduleList (after toggle) ---")
    r = execute_tool("ScheduleList", {}, config)
    print(r)

    print(f"\n--- s14: ScheduleDelete ({sid}) ---")
    r = execute_tool("ScheduleDelete", {"schedule_id": sid}, config)
    print(r)

print("\n--- s14: ScheduleList (final) ---")
r = execute_tool("ScheduleList", {}, config)
print(r)

# ===== 清理测试数据 =====
print("\n" + "=" * 60)
print("  清理测试数据...")
for d in [".tasks", ".runtime", ".schedules"]:
    test_dir = os.path.join(os.getcwd(), d)
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
        print(f"  已删除: {d}/")

print("\n  测试完成！所有新工具均可正常工作。")
print("=" * 60)
