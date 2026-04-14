#!/usr/bin/env python3
"""快速测试脚本 - 验证所有模块导入正常"""
import sys
import os

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from tools import register_builtin_tools, get_tool_schemas
from context import build_system_prompt
from providers import TextChunk, AssistantTurn, ToolCall
from compact import maybe_compact
from permissions import check_permission
from agent import AgentState, run

print("✓ All modules imported successfully!")

config = load_config()
print(f"✓ Config loaded: model={config['model']}, provider={config['provider']}")

register_builtin_tools()
schemas = get_tool_schemas()
print(f"✓ Registered {len(schemas)} tools: {[s['name'] for s in schemas]}")

prompt = build_system_prompt(config)
print(f"✓ System prompt built: {len(prompt)} chars")

state = AgentState(messages=[])
print(f"✓ AgentState created")

# 测试权限检查
tc = ToolCall(id="test", name="Read", params={"file_path": "test.py"})
print(f"✓ Permission check (Read): {check_permission(tc, config)}")

tc2 = ToolCall(id="test2", name="Bash", params={"command": "rm -rf /"})
print(f"✓ Permission check (dangerous Bash): {check_permission(tc2, config)}")

print("\n✅ All checks passed! Agent is ready to run.")
print("Run: python main.py")
