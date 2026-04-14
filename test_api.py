#!/usr/bin/env python3
"""测试智谱 API 实际调用"""
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from tools import register_builtin_tools, get_tool_schemas
from context import build_system_prompt
from providers import stream_llm, TextChunk, AssistantTurn
from agent import AgentState, run, ToolStart, ToolEnd, TurnDone, ErrorEvent

config = load_config()
register_builtin_tools()

print(f"Testing with: model={config['model']}, provider={config['provider']}")
print(f"API Key: {config['api_key'][:8]}...")
print(f"Base URL: {config['base_url']}")
print()

# 测试 1: 简单对话（不调用工具）
print("=" * 50)
print("Test 1: Simple conversation (no tools)")
print("=" * 50)

state = AgentState(messages=[])
user_input = "你好，请用一句话介绍你自己。"

print(f"User: {user_input}")
print("Assistant: ", end="", flush=True)

for event in run(user_input, state, config):
    if isinstance(event, TextChunk):
        print(event.text, end="", flush=True)
    elif isinstance(event, TurnDone):
        print(f"\n[Turn done, turns={state.turn_count}]")
    elif isinstance(event, ErrorEvent):
        print(f"\n[Error: {event.message}]")

print()
print()

# 测试 2: 工具调用
print("=" * 50)
print("Test 2: Tool call (list files)")
print("=" * 50)

state2 = AgentState(messages=[])
user_input2 = "请用 Glob 工具列出当前目录下的文件，pattern 用 '*.py'。然后告诉我有哪些 Python 文件。"

print(f"User: {user_input2}")
print("Assistant: ", end="", flush=True)

for event in run(user_input2, state2, config):
    if isinstance(event, TextChunk):
        print(event.text, end="", flush=True)
    elif isinstance(event, ToolStart):
        print(f"\n  [Tool: {event.name}({event.params})]")
        print(" 继续: ", end="", flush=True)
    elif isinstance(event, ToolEnd):
        preview = event.result[:200] + "..." if len(event.result) > 200 else event.result
        print(f"  [Result: {preview}]")
        print(" 继续: ", end="", flush=True)
    elif isinstance(event, TurnDone):
        print(f"\n[Turn done, turns={state2.turn_count}]")
    elif isinstance(event, ErrorEvent):
        print(f"\n[Error: {event.message}]")

print()
print("\nAll tests completed!")
