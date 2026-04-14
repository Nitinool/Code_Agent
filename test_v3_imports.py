"""Quick integration test for v3 s11-s14 subsystems"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test imports
print("1. Testing imports...")
from inbox import NotificationInbox, MessageEnvelope, get_inbox, init_inbox
from recovery import classify_error, decide_recovery, RecoveryBudget, RecoveryEvent
from tasks import (
    create_task, list_tasks, load_task, complete_task, fail_task, delete_task, is_ready,
    background_run, list_runtime_tasks, CronScheduler, 
    create_schedule, list_schedules, should_fire,
)
from tools import register_builtin_tools, register_memory_tools, register_task_tools, get_tool_schemas
from agent import create_agent_state, run, AgentState
from context import build_system_prompt
from compact import maybe_compact, force_compact
print("   All imports OK")

# Test tool registration
print("\n2. Testing tool registration...")
register_builtin_tools()
register_memory_tools()
register_task_tools()
schemas = get_tool_schemas()
names = [s["name"] for s in schemas]
print(f"   Registered {len(names)} tools:")
for name in names:
    print(f"     - {name}")

# Test inbox
print("\n3. Testing inbox...")
inbox = init_inbox()
inbox.push(MessageEnvelope(from_addr="test", to_addr="boss", content="hello"))
inbox.push(MessageEnvelope(from_addr="test2", to_addr="boss", content="world"))
assert inbox.pending_count() == 2
msgs = inbox.drain()
assert len(msgs) == 2
assert inbox.pending_count() == 0
print("   Inbox push/drain OK")

# Test recovery
print("\n4. Testing recovery state machine...")
budget = RecoveryBudget()
err = Exception("rate_limit: too many requests")
classified = classify_error(err)
assert classified.category == "rate_limit"
action = decide_recovery(classified, budget)
assert action.action == "retry"
print(f"   Recovery: {classified.category} -> {action.action} OK")

err2 = Exception("context_length_exceeded")
classified2 = classify_error(err2)
assert classified2.category == "prompt_too_long"
action2 = decide_recovery(classified2, budget)
assert action2.action == "compact"
print(f"   Recovery: {classified2.category} -> {action2.action} OK")

# Test work graph (s12)
print("\n5. Testing work graph...")
import tempfile
test_dir = tempfile.mkdtemp()
t1 = create_task(test_dir, "Setup database")
t2 = create_task(test_dir, "Write API", blocked_by=[t1.id])
t3 = create_task(test_dir, "Write tests", blocked_by=[t2.id])
print(f"   Created: {t1.id}, {t2.id}, {t3.id}")
assert is_ready(t1, test_dir) == True
assert is_ready(t2, test_dir) == False
assert is_ready(t3, test_dir) == False
complete_task(test_dir, t1.id, "DB ready")
t2_reload = load_task(test_dir, t2.id)
assert is_ready(t2_reload, test_dir) == True
print("   Work graph dependencies OK")

# Test cron parser (s14)
print("\n6. Testing cron parser...")
assert should_fire("* * * * *") == True  # always fires
print("   Cron parser OK")

# Test system prompt
print("\n7. Testing system prompt build...")
config = {"model": "qwen-plus", "cwd": test_dir, "provider": "qwen", "api_key": "test", "permission_mode": "normal"}
prompt = build_system_prompt(config)
assert "BackgroundRun" in prompt
assert "TaskCreate" in prompt
assert "ScheduleCreate" in prompt
print(f"   System prompt built ({len(prompt)} chars)")

# Test AgentState
print("\n8. Testing AgentState...")
state = create_agent_state(inbox=inbox)
assert isinstance(state, AgentState)
assert state.inbox is inbox
assert state.recovery_budget is not None
print("   AgentState OK")

# Cleanup
import shutil
shutil.rmtree(test_dir, ignore_errors=True)

print("\n" + "="*50)
print("ALL TESTS PASSED! v3 s11-s14 subsystems ready.")
print("="*50)
