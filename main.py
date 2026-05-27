#!/usr/bin/env python3
# main.py — REPL 入口
# 启动交互式对话循环，处理命令行参数，渲染流式输出

import sys
import os
import argparse

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 确保可以导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import register_builtin_tools
register_builtin_tools()

from config import load_config, save_config, detect_provider, PROVIDER_CONFIG
from agent import (
    AgentState, run_agent_turn,
    TextEvent, ThinkingEvent, ToolCallEvent, ToolResultEvent,
    PermissionRequestEvent, TurnEndEvent, DoneEvent,
)
from permissions import format_permission_request
from session import save_session, load_session, list_sessions, delete_session, auto_save_name
from skills import list_skills, list_namespaces, resolve_skill_name, load_skills, get_namespace_skills


# ===== UI 颜色（ANSI）=====

C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"
C_RESET = "\033[0m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{C_RESET}"


# ===== Banner & Help =====

def print_banner(config: dict):
    """打印启动横幅"""
    print()
    print(color("╔══════════════════════════════════════════════╗", C_CYAN))
    print(color("║   🤖 My Agent — AI Coding Assistant         ║", C_CYAN))
    print(color("╚══════════════════════════════════════════════╝", C_CYAN))
    print()
    print(f"  {color('Model:', C_DIM)}     {color(config['model'], C_BOLD)}")
    print(f"  {color('Provider:', C_DIM)}  {config['provider']}")
    print(f"  {color('Cwd:', C_DIM)}       {config['cwd']}")
    print(f"  {color('Mode:', C_DIM)}      {config['permission_mode']}")

    api_key = config.get("api_key", "")
    if api_key:
        masked = api_key[:8] + "..." if len(api_key) > 8 else "***"
        print(f"  {color('API Key:', C_DIM)}   {masked}")
    else:
        print(f"  {color('API Key:', C_DIM)}   {color('⚠ NOT SET', C_RED)}")

    active = config.get("active_skills", [])
    if active:
        print(f"  {color('Skills:', C_DIM)}    {len(active)} active ({', '.join(active[:3])}{'...' if len(active) > 3 else ''})")

    print()
    print(color("  Commands: /help /save /load /list /clear /model /skill /quit", C_DIM))
    print()


def print_help():
    """打印命令帮助"""
    print("""
Available commands:
  /help, /h              Show this help
  /quit, /exit, /q       Exit the agent (auto-saves conversation)
  /clear                 Clear conversation history
  /status                Show current status

  Conversation Management:
  /save [name]           Save current conversation (auto-name if omitted)
  /load <name>           Load a saved conversation
  /list                  List all saved conversations
  /delete <name>         Delete a saved conversation

  Skills:
  /skill list            List all available skills (grouped by namespace)
  /skill info <name>     Show skill details
  /skill enable <name>   Enable a skill or namespace (e.g., "superpowers")
  /skill disable <name>  Disable a skill or namespace

  Settings:
  /model <name>          Switch model (e.g., glm-4-plus, qwen-plus, gpt-4o)
  /accept-all            Auto-approve all tool calls
  /normal                Require permission for risky tool calls
  /cwd <path>            Change working directory
""")


# ===== 权限请求 =====

def ask_permission(tool_call) -> bool:
    """请求用户授权"""
    print()
    print(color(format_permission_request(tool_call), C_YELLOW))
    try:
        answer = input(color("  Allow? [y/N]: ", C_YELLOW)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


# ===== 事件渲染 =====

def render_events(events_generator, state):
    """渲染 agent 事件流"""
    printed_marker = False

    for event in events_generator:
        if isinstance(event, TextEvent):
            if not printed_marker:
                print(color("\n🤖 ", C_GREEN), end="", flush=True)
                printed_marker = True
            print(event.text, end="", flush=True)

        elif isinstance(event, ThinkingEvent):
            if not printed_marker:
                print(color("\n💭 ", C_DIM), end="", flush=True)
                printed_marker = True
            print(color(event.text, C_DIM), end="", flush=True)

        elif isinstance(event, ToolCallEvent):
            print()
            print(color(f"  ⚙ {event.name}", C_MAGENTA), end="")
            if event.name == "Read" and "file_path" in event.params:
                print(color(f" → {event.params['file_path']}", C_DIM))
            elif event.name == "Write" and "file_path" in event.params:
                print(color(f" → {event.params['file_path']}", C_DIM))
            elif event.name == "Bash" and "command" in event.params:
                print(color(f" → {event.params['command'][:80]}", C_DIM))
            elif event.name == "Glob" and "pattern" in event.params:
                print(color(f" → {event.params['pattern']}", C_DIM))
            elif event.name == "Grep" and "pattern" in event.params:
                print(color(f" → /{event.params['pattern']}/", C_DIM))
            else:
                print()
            printed_marker = False

        elif isinstance(event, ToolResultEvent):
            lines = event.result.split("\n")
            preview_lines = lines[:5]
            for line in preview_lines:
                print(color(f"    {line[:120]}", C_DIM))
            if len(lines) > 5:
                print(color(f"    ... ({len(lines) - 5} more lines)", C_DIM))

        elif isinstance(event, PermissionRequestEvent):
            pass

        elif isinstance(event, TurnEndEvent):
            if event.has_more:
                printed_marker = False

        elif isinstance(event, DoneEvent):
            print()
            return


# ===== Skill 命令处理 =====

def _handle_skill_command(arg: str, config: dict) -> None:
    """处理 /skill <subcommand> [args]"""
    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    subarg = parts[1].strip() if len(parts) > 1 else ""

    cwd = config.get("cwd")
    active = config.get("active_skills", [])

    if subcmd == "list":
        skills = list_skills(cwd)
        namespaces = list_namespaces(cwd)
        if not skills:
            print(color("  No skills found.", C_DIM))
            print(color("  Place skills in skills/<namespace>/<name>/SKILL.md", C_DIM))
            return

        # 按命名空间分组显示
        ns_active = {}  # namespace → active_count
        for ns_info in namespaces:
            ns = ns_info["namespace"]
            ns_skills = ns_info["skills"]
            ns_active[ns] = sum(1 for s in ns_skills if s in active)

        print()
        for ns_info in namespaces:
            ns = ns_info["namespace"]
            count = ns_info["skill_count"]
            a_count = ns_active.get(ns, 0)
            ns_status = color("✓", C_GREEN) if a_count == count else color(f"{a_count}/{count}", C_YELLOW) if a_count > 0 else color("○", C_DIM)
            print(f"  {ns_status} {color(ns, C_BOLD)} ({count} skills)")
            for full_name in ns_info["skills"]:
                from skills import get_skill
                s = get_skill(full_name, cwd)
                if s:
                    s_status = color("✓", C_GREEN) if full_name in active else color("○", C_DIM)
                    short = s.name
                    desc = s.description[:80] + "..." if len(s.description) > 80 else s.description
                    print(f"      {s_status} {color(short, C_CYAN)} — {color(desc, C_DIM)}")
        print()

    elif subcmd == "info":
        if not subarg:
            print(color("  Usage: /skill info <name>", C_RED))
            return
        resolved = resolve_skill_name(subarg, cwd)
        if not resolved:
            print(color(f"  ✗ Skill not found: {subarg}", C_RED))
            return
        from skills import get_skill
        skill = get_skill(resolved, cwd)
        if not skill:
            print(color(f"  ✗ Skill not found: {resolved}", C_RED))
            return
        is_active = resolved in active
        status = color("✓ active", C_GREEN) if is_active else color("○ inactive", C_DIM)
        print()
        print(color(f"  🧩 {skill.full_name}  {status}", C_BOLD))
        print(f"  {color('Source:', C_DIM)}  {skill.source} ({skill.path})")
        print(f"  {color('Description:', C_DIM)} {skill.description}")
        body_lines = skill.body.strip().split("\n")
        preview = "\n".join(body_lines[:20])
        if len(body_lines) > 20:
            preview += f"\n  ... ({len(body_lines) - 20} more lines)"
        print(color(f"\n  --- Preview ---", C_DIM))
        for line in preview.split("\n"):
            print(f"  {color(line[:120], C_DIM)}")
        print()

    elif subcmd == "enable":
        if not subarg:
            print(color("  Usage: /skill enable <name|namespace>", C_RED))
            return

        resolved = resolve_skill_name(subarg, cwd)

        # 检查是否是命名空间
        namespaces = list_namespaces(cwd)
        ns_names = [n["namespace"] for n in namespaces]
        is_namespace = subarg in ns_names

        if is_namespace:
            # 启用整个命名空间
            ns_skills = get_namespace_skills(subarg, cwd)
            new_skills = [s for s in ns_skills if s not in active]
            if not new_skills:
                print(color(f"  All skills in '{subarg}' are already active.", C_YELLOW))
                return
            active.extend(new_skills)
            config["active_skills"] = active
            save_config(config)
            print(color(f"  ✓ Enabled namespace '{subarg}' ({len(new_skills)} skills):", C_GREEN))
            for s in new_skills:
                print(color(f"    + {s}", C_DIM))
            print(color(f"    (will take effect on next message)", C_DIM))
        elif resolved:
            # 启用单个 skill
            if resolved in active:
                print(color(f"  Skill '{resolved}' is already active.", C_YELLOW))
                return
            active.append(resolved)
            config["active_skills"] = active
            save_config(config)
            print(color(f"  ✓ Skill '{resolved}' enabled.", C_GREEN))
            print(color(f"    (will take effect on next message)", C_DIM))
        else:
            print(color(f"  ✗ Skill or namespace not found: {subarg}", C_RED))
            print(color(f"  Use /skill list to see available skills.", C_DIM))

    elif subcmd == "disable":
        if not subarg:
            print(color("  Usage: /skill disable <name|namespace>", C_RED))
            return

        resolved = resolve_skill_name(subarg, cwd)

        # 检查是否是命名空间
        namespaces = list_namespaces(cwd)
        ns_names = [n["namespace"] for n in namespaces]
        is_namespace = subarg in ns_names

        if is_namespace:
            # 禁用整个命名空间
            ns_skills = get_namespace_skills(subarg, cwd)
            removed = [s for s in ns_skills if s in active]
            if not removed:
                print(color(f"  No skills in '{subarg}' are active.", C_YELLOW))
                return
            for s in removed:
                active.remove(s)
            config["active_skills"] = active
            save_config(config)
            print(color(f"  ✓ Disabled namespace '{subarg}' ({len(removed)} skills):", C_GREEN))
            for s in removed:
                print(color(f"    - {s}", C_DIM))
        elif resolved:
            # 禁用单个 skill
            if resolved not in active:
                print(color(f"  Skill '{resolved}' is not active.", C_YELLOW))
                return
            active.remove(resolved)
            config["active_skills"] = active
            save_config(config)
            print(color(f"  ✓ Skill '{resolved}' disabled.", C_GREEN))
        else:
            print(color(f"  ✗ Skill or namespace not found: {subarg}", C_RED))
            print(color(f"  Use /skill list to see available skills.", C_DIM))

    else:
        print(color("  Usage:", C_YELLOW))
        print(color("    /skill list              List available skills", C_DIM))
        print(color("    /skill info <name>       Show skill details", C_DIM))
        print(color("    /skill enable <name>     Enable a skill or namespace", C_DIM))
        print(color("    /skill disable <name>    Disable a skill or namespace", C_DIM))


# ===== 斜杠命令处理 =====

def handle_command(cmd_raw: str, state: AgentState, config: dict) -> bool:
    """
    处理斜杠命令。
    返回 False 表示退出程序，True 表示继续。
    """
    cmd_raw = cmd_raw.strip()
    parts = cmd_raw.split(maxsplit=1)
    if not parts:
        return True

    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit", "/q"):
        if state.messages:
            name = auto_save_name()
            try:
                save_session(name, state.messages, config)
                print(color(f"  💾 Auto-saved as '{name}'", C_GREEN))
            except Exception as e:
                print(color(f"  ⚠ Auto-save failed: {e}", C_YELLOW))
        print(color("  👋 Goodbye!", C_GREEN))
        return False

    elif cmd in ("/help", "/h", "/?"):
        print_help()

    elif cmd == "/clear":
        state.messages.clear()
        state.turn_count = 0
        state.total_input_tokens = 0
        state.total_output_tokens = 0
        print(color("  🧹 Conversation cleared.", C_GREEN))

    elif cmd == "/status":
        print(f"  Model: {config.get('model', 'unknown')}")
        print(f"  Provider: {config.get('provider', 'unknown')}")
        print(f"  CWD: {config.get('cwd', '.')}")
        print(f"  Permission mode: {config.get('permission_mode', 'normal')}")
        print(f"  Messages: {len(state.messages)}")
        print(f"  Turn count: {state.turn_count}")
        active = config.get("active_skills", [])
        if active:
            print(f"  Active skills: {', '.join(active)}")

    elif cmd == "/save":
        name = arg or auto_save_name()
        try:
            result = save_session(name, state.messages, config)
            print(color(f"  💾 {result}", C_GREEN))
        except Exception as e:
            print(color(f"  ✗ Save failed: {e}", C_RED))

    elif cmd == "/load":
        if not arg:
            print(color("  Usage: /load <name>", C_RED))
            return True
        data = load_session(arg)
        if data is None:
            print(color(f"  ✗ Session not found: {arg}", C_RED))
            print(color(f"  Use /list to see available sessions.", C_DIM))
        else:
            state.messages = data.get("messages", [])
            state.turn_count = 0
            state.total_input_tokens = 0
            state.total_output_tokens = 0
            print(color(f"  📂 Loaded '{data.get('name', arg)}' ({data.get('message_count', 0)} messages)", C_GREEN))
            if data.get("summary"):
                print(color(f"    Summary: {data['summary']}", C_DIM))

    elif cmd in ("/list", "/sessions", "/history"):
        sessions = list_sessions()
        if not sessions:
            print(color("  No saved sessions.", C_DIM))
        else:
            print()
            print(color(f"  📚 Saved sessions ({len(sessions)}):", C_BOLD))
            for s in sessions:
                date = s.get("created_at", "")[:16]
                msgs = s.get("message_count", 0)
                print(f"    {color(s['name'], C_CYAN)} - {msgs} msgs - {color(date, C_DIM)}")
                if s.get("summary"):
                    print(f"      {color(s['summary'], C_DIM)}")
            print()

    elif cmd == "/delete":
        if not arg:
            print(color("  Usage: /delete <name>", C_RED))
            return True
        result = delete_session(arg)
        print(color(f"  🗑 {result}", C_GREEN))

    elif cmd == "/accept-all":
        config["permission_mode"] = "accept-all"
        print(color("  ✓ Switched to accept-all mode.", C_GREEN))

    elif cmd == "/normal":
        config["permission_mode"] = "normal"
        print(color("  ✓ Switched to normal mode (will ask permission).", C_GREEN))

    elif cmd == "/model":
        if not arg:
            print(color(f"  Current model: {config['model']}", C_CYAN))
            print(color("  Usage: /model <name>  (e.g., glm-4-plus, qwen-plus, gpt-4o)", C_DIM))
            return True
        config["model"] = arg
        provider = detect_provider(arg)
        config["provider"] = provider
        pconf = PROVIDER_CONFIG[provider]
        config["base_url"] = pconf["base_url"]
        config["api_key"] = os.getenv(pconf["env_key"], config.get("api_key", ""))
        print(color(f"  ✓ Switched to model: {arg} (provider: {provider})", C_GREEN))
        if not config["api_key"]:
            print(color(f"  ⚠ API key not set for {provider} (env: {pconf['env_key']})", C_YELLOW))

    elif cmd == "/cwd":
        if not arg:
            print(color(f"  Current cwd: {config['cwd']}", C_CYAN))
            return True
        if os.path.isdir(arg):
            config["cwd"] = os.path.abspath(arg)
            print(color(f"  ✓ Working directory: {config['cwd']}", C_GREEN))
        else:
            print(color(f"  ✗ Directory not found: {arg}", C_RED))

    elif cmd == "/skill":
        _handle_skill_command(arg, config)

    else:
        print(color(f"  Unknown command: {cmd}", C_RED))
        print(color("  Type /help for available commands.", C_DIM))

    return True


# ===== 主入口 =====

def main():
    """主 REPL 循环"""
    parser = argparse.ArgumentParser(description="My Agent - AI Coding Assistant")
    parser.add_argument("--model", "-m", help="Model name (e.g., qwen-plus, glm-4-plus, gpt-4o)")
    parser.add_argument("--cwd", "-d", help="Working directory", default=os.getcwd())
    parser.add_argument("--accept-all", "-a", action="store_true", help="Auto-approve all tool calls")
    parser.add_argument("--provider", "-p", help="Provider (qwen, zhipu, openai)")
    args = parser.parse_args()

    # 加载配置
    config = load_config(cwd=args.cwd)

    # 命令行参数覆盖
    if args.model:
        config["model"] = args.model
        provider = detect_provider(args.model)
        config["provider"] = provider
        pconf = PROVIDER_CONFIG[provider]
        config["base_url"] = pconf["base_url"]
        config["api_key"] = os.getenv(pconf["env_key"], config.get("api_key", ""))

    if args.provider:
        config["provider"] = args.provider
        pconf = PROVIDER_CONFIG.get(args.provider, {})
        config["base_url"] = pconf.get("base_url")

    if args.accept_all:
        config["permission_mode"] = "accept-all"

    # 创建 AgentState
    state = AgentState()

    # 打印横幅
    print_banner(config)

    if not config.get("api_key"):
        print(color("  ⚠ WARNING: API key is not configured!", C_YELLOW))
        print(color("  Set the appropriate environment variable or create a .env file:", C_DIM))
        print(color("    QWEN_API_KEY=xxx     (for Qwen / Tongyi)", C_DIM))
        print(color("    ZHIPU_API_KEY=xxx    (for GLM / Zhipu)", C_DIM))
        print(color("    OPENAI_API_KEY=xxx   (for OpenAI GPT)", C_DIM))
        print()

    # REPL 循环
    while True:
        try:
            user_input = input(color("» ", C_CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(color("  👋 Goodbye!", C_GREEN))
            break

        if not user_input:
            continue

        # 斜杠命令
        if user_input.startswith("/"):
            if not handle_command(user_input, state, config):
                break
            continue

        # 运行 Agent
        try:
            events = run_agent_turn(
                state=state,
                user_input=user_input,
                config=config,
                permission_callback=ask_permission,
            )
            render_events(events, state)
        except KeyboardInterrupt:
            print()
            print(color("  [Interrupted]", C_YELLOW))
        except Exception as e:
            print()
            print(color(f"  ✗ Unexpected error: {e}", C_RED))


if __name__ == "__main__":
    main()
