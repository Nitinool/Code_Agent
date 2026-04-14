#!/usr/bin/env python3
# main.py — CLI 入口，把所有东西串起来
# v3: 事件驱动 + s11-s14 子系统集成

import sys
import os
import threading
import time

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 确保可以导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from agent import (
    AgentState, create_agent_state, run,
    TextChunk, ToolStart, ToolEnd, TurnDone, ErrorEvent,
    InboxDrainEvent,
)
from recovery import RecoveryEvent
from tools import register_builtin_tools, register_memory_tools, register_task_tools, register_team_tools
from memory import load_memory, load_memory_summary
from session import save_session, load_session, list_sessions, delete_session, auto_save_name
from inbox import init_inbox, get_inbox
from tasks import (
    CronScheduler, list_tasks, list_runtime_tasks, list_schedules,
    load_task, load_runtime_task,
)
from team import (
    spawn_teammate, shutdown_all_teammates, get_all_teammates,
    list_team_members, get_teammate,
)


# ===== 全局调度器 =====
_scheduler: CronScheduler = None
_inbox_notifier_running = threading.Event()


def _inbox_notifier_loop(state: AgentState, running: threading.Event):
    """
    后台收件箱通知线程 — 在 REPL 等待用户输入时实时打印收件箱消息。
    
    当 Cron 调度器或后台任务把消息推入 Inbox 后，
    这个线程会在 2 秒内检测到并直接打印到终端，
    不需要等用户发送下一条消息。
    """
    from inbox import get_inbox
    
    while running.is_set():
        try:
            inbox = get_inbox()
            if inbox.has_pending():
                msgs = inbox.drain()
                for msg in msgs:
                    # 打印到终端（插入到当前输入行之前）
                    preview = msg.content[:200].replace("\n", " ")
                    print(f"\n  📬 [{msg.from_addr}] {preview}")
                    print("» ", end="", flush=True)  # 重新打印提示符
        except Exception:
            pass
        time.sleep(2)


# ===== 斜杠命令处理 =====

def handle_slash_command(cmd_raw: str, state: AgentState, config: dict) -> bool:
    """
    处理斜杠命令。返回 True 表示已处理，False 表示退出。
    """
    global _scheduler
    
    cmd_raw = cmd_raw.strip()
    cmd = cmd_raw.lower()
    
    if cmd in ("/exit", "/quit", "/q"):
        # 自动保存当前对话（如果有内容）
        if state.messages:
            name = auto_save_name()
            result = save_session(name, state.messages, config)
            print(f"  Auto-saved: {result}")
        # 停止调度器
        if _scheduler:
            _scheduler.stop()
        print("Goodbye!")
        return False
    
    elif cmd in ("/clear", "/reset"):
        state.messages.clear()
        state.turn_count = 0
        state.total_input_tokens = 0
        state.total_output_tokens = 0
        print("  ✓ Conversation cleared.")
    
    elif cmd in ("/help", "/h", "/?"):
        print_help()
    
    elif cmd == "/status":
        print(f"  Model: {config.get('model', 'unknown')}")
        print(f"  Provider: {config.get('provider', 'unknown')}")
        print(f"  CWD: {config.get('cwd', '.')}")
        print(f"  Permission mode: {config.get('permission_mode', 'normal')}")
        print(f"  Messages: {len(state.messages)}")
        print(f"  Turn count: {state.turn_count}")
        print(f"  Total tokens: {state.total_input_tokens} in / {state.total_output_tokens} out")
        # 显示收件箱状态
        inbox = get_inbox()
        if inbox.pending_count() > 0:
            print(f"  Inbox: {inbox.pending_count()} pending messages")
    
    elif cmd == "/accept-all":
        config["permission_mode"] = "accept-all"
        print("  ✓ Switched to accept-all mode. All tool calls will be auto-approved.")
    
    elif cmd == "/normal":
        config["permission_mode"] = "normal"
        print("  ✓ Switched to normal mode. Tool calls need permission.")
    
    elif cmd.startswith("/model "):
        model = cmd.split(" ", 1)[1].strip()
        config["model"] = model
        # 更新 provider
        from config import detect_provider, PROVIDER_CONFIG
        provider = detect_provider(model)
        config["provider"] = provider
        pconf = PROVIDER_CONFIG[provider]
        config["base_url"] = pconf["base_url"]
        print(f"  ✓ Switched to model: {model} (provider: {provider})")
    
    elif cmd.startswith("/cwd "):
        new_cwd = cmd.split(" ", 1)[1].strip()
        if os.path.isdir(new_cwd):
            config["cwd"] = os.path.abspath(new_cwd)
            # 重启调度器到新目录
            if _scheduler:
                _scheduler.stop()
            _scheduler = CronScheduler(config["cwd"])
            _scheduler.start()
            print(f"  ✓ Working directory: {config['cwd']}")
        else:
            print(f"  ✗ Directory not found: {new_cwd}")
    
    elif cmd == "/memory":
        mem_summary = load_memory_summary()
        if mem_summary:
            print(f"  {mem_summary}")
        else:
            print("  No memories saved yet.")
    
    # ===== 收件箱命令 =====
    elif cmd == "/inbox":
        inbox = get_inbox()
        count = inbox.pending_count()
        if count > 0:
            print(f"  {count} pending message(s) in inbox.")
            msgs = inbox.drain()
            for msg in msgs:
                preview = msg.content[:100].replace("\n", " ")
                print(f"  [{msg.from_addr}] {preview}...")
        else:
            print("  Inbox is empty.")
    
    # ===== 任务管理命令 =====
    elif cmd in ("/tasks", "/task-list"):
        cwd = config.get("cwd", ".")
        tasks = list_tasks(cwd)
        if not tasks:
            print("  No tasks.")
        else:
            print(f"  Tasks ({len(tasks)}):")
            for t in tasks:
                ready = " ✓" if t.status == "pending" and not t.blockedBy else ""
                owner = f" → {t.owner}" if t.owner else ""
                print(f"    {t.id}  [{t.status}]{ready}  {t.subject}{owner}")
    
    elif cmd in ("/bg", "/background"):
        cwd = config.get("cwd", ".")
        rts = list_runtime_tasks(cwd)
        if not rts:
            print("  No background tasks.")
        else:
            running = [r for r in rts if r.status == "running"]
            done = [r for r in rts if r.status != "running"]
            if running:
                print(f"  Running ({len(running)}):")
                for r in running:
                    print(f"    {r.id}  {r.command[:60]}")
            if done:
                print(f"  Recent ({min(len(done), 10)}):")
                for r in done[:10]:
                    emoji = "✓" if r.status == "completed" else "✗"
                    print(f"    {emoji} {r.id}  [{r.status}]  {r.command[:50]}")
    
    elif cmd in ("/schedules", "/cron"):
        cwd = config.get("cwd", ".")
        schedules = list_schedules(cwd)
        if not schedules:
            print("  No schedules.")
        else:
            print(f"  Schedules ({len(schedules)}):")
            for s in schedules:
                enabled = "ON" if s.enabled else "OFF"
                last = s.last_fired_at or "never"
                print(f"    {s.id}  [{enabled}]  {s.cron_expr}  \"{s.prompt[:40]}\"  last: {last}")
    
    # ===== 对话管理 =====
    elif cmd == "/save":
        name = auto_save_name()
        result = save_session(name, state.messages, config)
        print(f"  ✓ {result}")
    
    elif cmd.startswith("/save "):
        name = cmd_raw.split(" ", 1)[1].strip()
        result = save_session(name, state.messages, config)
        print(f"  ✓ {result}")
    
    elif cmd.startswith("/load "):
        name = cmd_raw.split(" ", 1)[1].strip()
        session_data = load_session(name)
        if session_data is None:
            print(f"  ✗ Session not found: {name}")
            print(f"  Use /sessions to list available sessions.")
        else:
            state.messages = session_data.get("messages", [])
            state.turn_count = 0
            state.total_input_tokens = 0
            state.total_output_tokens = 0
            msg_count = len(state.messages)
            summary = session_data.get("summary", "")
            saved_model = session_data.get("model", "")
            saved_at = session_data.get("created_at", "")
            print(f"  ✓ Loaded session: {session_data.get('name', name)}")
            print(f"    Saved at: {saved_at}")
            print(f"    Model: {saved_model}")
            print(f"    Messages: {msg_count}")
            if summary:
                print(f"    Summary: {summary}")
    
    elif cmd in ("/sessions", "/history"):
        sessions = list_sessions()
        if not sessions:
            print("  No saved sessions.")
        else:
            print(f"  Saved sessions ({len(sessions)}):")
            print(f"  {'No.':<4} {'Name':<35} {'Date':<20} {'Msgs':<6} {'Summary'}")
            print(f"  {'-'*4} {'-'*35} {'-'*20} {'-'*6} {'-'*30}")
            for i, s in enumerate(sessions, 1):
                name = s["name"][:33]
                date = s.get("created_at", "")[:19]
                msgs = str(s.get("message_count", 0))
                summary = s.get("summary", "")[:28]
                print(f"  {i:<4} {name:<35} {date:<20} {msgs:<6} {summary}")
            print()
            print("  Use /load <name> to load a session.")
    
    elif cmd.startswith("/delete-session "):
        name = cmd_raw.split(" ", 1)[1].strip()
        result = delete_session(name)
        print(f"  {result}")
    
    # ===== 团队管理命令 =====
    elif cmd in ("/team", "/teammates"):
        members = list_team_members(config["cwd"])
        active = get_all_teammates()
        if not members:
            print("  No team members. Use /team-init to spawn default workers.")
        else:
            print(f"  Team Members ({len(members)}, {len(active)} active):")
            for m in members:
                h = active.get(m.name)
                if h:
                    info = h.get_info()
                    task_str = f"task={info['current_task']}" if info['current_task'] else "idle"
                    print(f"    {m.name}  [{info['status']}]  {m.role}  {task_str}  inbox={info['pending_inbox']}")
                else:
                    print(f"    {m.name}  [offline]  {m.role}")
    
    elif cmd == "/team-init":
        active = get_all_teammates()
        spawned = []
        worker_configs = [
            ("worker-1", "worker", "Coder - writes and modifies code"),
            ("worker-2", "worker", "Reviewer - reviews code and runs tests"),
        ]
        for name, role, desc in worker_configs:
            if name not in active:
                try:
                    handle = spawn_teammate(config["cwd"], name, role, desc, config)
                    spawned.append(name)
                except Exception as e:
                    print(f"  ✗ Failed to spawn {name}: {e}")
            else:
                print(f"  {name} is already running")
        if spawned:
            print(f"  ✓ Spawned: {', '.join(spawned)}")
    
    elif cmd == "/team-stop":
        active = get_all_teammates()
        if not active:
            print("  No active teammates.")
        else:
            shutdown_all_teammates()
            print(f"  ✓ Shut down: {', '.join(active.keys())}")
    
    else:
        print(f"  Unknown command: {cmd}")
        print("  Type /help for available commands.")
    
    return True


def print_help():
    """打印帮助信息"""
    print("""
Available commands:
  /help, /h              Show this help
  /exit, /quit, /q       Exit the agent (auto-saves conversation)
  /clear, /reset         Clear conversation history
  /status                Show current status

  Conversation Management:
  /save [name]           Save current conversation (auto-name if omitted)
  /load <name>           Load a saved conversation
  /sessions              List all saved conversations
  /delete-session <name> Delete a saved conversation

  Task & Background:
  /tasks                 List work graph tasks
  /bg                    List background runtime tasks
  /schedules             List cron schedules
  /inbox                 Show and drain pending inbox messages

  Memory:
  /memory                Show saved user preferences

  Settings:
  /accept-all            Auto-approve all tool calls
  /normal                Require permission for tool calls
  /model <name>          Switch model (e.g., /model glm-4, /model qwen-plus)
  /cwd <path>            Change working directory

Tips:
  - BackgroundRun tool executes long commands without blocking the REPL
  - TaskCreate/TaskComplete manage a persistent work graph with dependencies
  - ScheduleCreate sets up cron-triggered prompts (e.g., '*/5 * * * *' every 5 min)
  - Recovery from LLM errors (rate limit, timeout, context overflow) is automatic
""")


def print_banner(config: dict):
    """打印启动横幅"""
    print()
    print("╔══════════════════════════════════════════╗")
    print("║     My Agent - Autonomous Agent v3       ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Model: {config.get('model', 'unknown')}")
    print(f"  Provider: {config.get('provider', 'unknown')}")
    print(f"  Working directory: {config.get('cwd', '.')}")
    print(f"  Permission: {config.get('permission_mode', 'normal')}")
    
    api_key = config.get("api_key", "")
    if api_key:
        masked = api_key[:8] + "..." if len(api_key) > 8 else "***"
        print(f"  API Key: {masked}")
    else:
        print("  ⚠ API Key not set!")
    
    # 显示子系统状态
    print(f"  Subsystems: Recovery(s11) ✓ | WorkGraph(s12) ✓ | Background(s13) ✓ | Scheduler(s14) ✓ | Team(s15-s17) ✓")
    
    print()
    print("  Type your message, or /help for commands.")
    print()


# ===== 主入口 =====

def main():
    """主 REPL 循环"""
    global _scheduler
    
    import argparse
    
    parser = argparse.ArgumentParser(description="My Agent - Autonomous Agent v3")
    parser.add_argument("--model", "-m", help="Model name (e.g., qwen-plus, glm-4-plus)")
    parser.add_argument("--cwd", "-d", help="Working directory", default=os.getcwd())
    parser.add_argument("--accept-all", "-a", action="store_true", help="Auto-approve all tool calls")
    parser.add_argument("--provider", "-p", help="Provider (qwen, zhipu, openai)")
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(cwd=args.cwd)
    
    # 命令行参数覆盖
    if args.model:
        config["model"] = args.model
        from config import detect_provider, PROVIDER_CONFIG
        provider = detect_provider(args.model)
        config["provider"] = provider
        pconf = PROVIDER_CONFIG[provider]
        config["base_url"] = pconf["base_url"]
    
    if args.provider:
        config["provider"] = args.provider
        from config import PROVIDER_CONFIG
        pconf = PROVIDER_CONFIG.get(args.provider, {})
        config["base_url"] = pconf.get("base_url")
    
    if args.accept_all:
        config["permission_mode"] = "accept-all"
    
    # ===== 初始化子系统 =====
    
    # 初始化收件箱
    inbox = init_inbox()
    
    # 注册所有工具（包括 s12/s13/s14）
    register_builtin_tools()
    register_memory_tools()
    register_task_tools()
    register_team_tools()
    
    # 创建 AgentState（含收件箱和恢复预算）
    state = create_agent_state(inbox=inbox)
    
    # 加载记忆到 config
    config["_memory"] = load_memory()
    
    # 启动 Cron 调度器 (s14)
    _scheduler = CronScheduler(config["cwd"], check_interval=30)
    _scheduler.start()
    
    # 打印横幅
    print_banner(config)
    
    # 检查 API Key
    if not config.get("api_key"):
        print("  ⚠ WARNING: API key is not configured!")
        print(f"  Please set environment variable or create .env file:")
        print(f"    QWEN_API_KEY=xxx     (for Qwen)")
        print(f"    ZHIPU_API_KEY=xxx    (for GLM)")
        print()
    
    # 启动后台收件箱通知线程（在 REPL 等待输入时实时打印通知）
    _inbox_notifier_running.set()
    notifier_thread = threading.Thread(
        target=_inbox_notifier_loop,
        args=(state, _inbox_notifier_running),
        daemon=True,
        name="inbox-notifier",
    )
    notifier_thread.start()
    
    # REPL 循环
    while True:
        try:
            user_input = input("» ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        # 斜杠命令
        if user_input.startswith("/"):
            should_continue = handle_slash_command(user_input, state, config)
            if not should_continue:
                break
            continue
        
        # 运行 Agent
        try:
            for event in run(user_input, state, config):
                if isinstance(event, TextChunk):
                    print(event.text, end="", flush=True)
                
                elif isinstance(event, RecoveryEvent):
                    # 恢复事件
                    print(f"\n  🔄 {event.message}")
                
                elif isinstance(event, InboxDrainEvent):
                    # 收件箱排空事件
                    print(f"\n  📬 Inbox: {event.count} message(s) drained")
                    for preview in event.previews:
                        print(f"    {preview}")
                
                elif isinstance(event, ToolStart):
                    param_preview = ""
                    if event.params:
                        first_val = list(event.params.values())[0] if event.params else ""
                        if isinstance(first_val, str):
                            param_preview = first_val[:60]
                            if len(first_val) > 60:
                                param_preview += "..."
                        elif isinstance(first_val, list):
                            param_preview = f"[{len(first_val)} items]"
                    print(f"\n  ⚙ {event.name}({param_preview})")
                
                elif isinstance(event, ToolEnd):
                    result_len = len(event.result)
                    print(f"  ✓ {event.name} → {result_len} chars")
                    if event.name in ("Bash",) and result_len < 500:
                        for line in event.result.strip().split("\n"):
                            print(f"    {line}")
                
                elif isinstance(event, TurnDone):
                    if state.total_input_tokens or state.total_output_tokens:
                        print(f"\n  [turns: {state.turn_count}]")
                
                elif isinstance(event, ErrorEvent):
                    print(f"\n  ✗ {event.message}")
        except KeyboardInterrupt:
            print("\n  [Interrupted]")
        except Exception as e:
            print(f"\n  ✗ Unexpected error: {e}")
        
        print()  # 空行分隔
    
    # 清理
    _inbox_notifier_running.clear()
    shutdown_all_teammates()
    if _scheduler:
        _scheduler.stop()


if __name__ == "__main__":
    main()
