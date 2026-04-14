#!/usr/bin/env python3
# test_v3_team.py — 离线测试多 Agent 架构 (不需要 API Key)
# 测试：名册管理、消息通道、原子认领、协议流转

import sys
import os
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 注册所有工具
from tools import register_builtin_tools, register_memory_tools, register_task_tools, register_team_tools
register_builtin_tools()
register_memory_tools()
register_task_tools()
register_team_tools()

from tasks import (
    create_task, list_tasks, complete_task, fail_task,
    load_task, claim_task, is_claimable, is_ready,
)
from team import (
    TeamMember, add_team_member, list_team_members, remove_team_member,
    send_to_teammate, drain_teammate_inbox, peek_teammate_inbox,
    ProtocolEnvelope, RequestRecord, create_request, resolve_request,
    load_request, list_requests,
    create_shutdown_protocol, create_task_assign_protocol,
    create_plan_approval_protocol,
)
from inbox import init_inbox, get_inbox

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✓ {name}")
        passed += 1
    else:
        print(f"  ✗ {name}  — {detail}")
        failed += 1


# ===== 准备临时工作目录 =====
tmpdir = tempfile.mkdtemp(prefix="test_team_")
print(f"\n📁 测试目录: {tmpdir}\n")

try:
    # ================================================================
    print("=== 1. 名册管理 (s15) ===")
    # ================================================================
    
    m1 = TeamMember(name="boss", role="boss", role_desc="Team coordinator")
    m2 = TeamMember(name="worker-1", role="worker", role_desc="Coder")
    m3 = TeamMember(name="worker-2", role="worker", role_desc="Reviewer")
    
    add_team_member(tmpdir, m1)
    add_team_member(tmpdir, m2)
    add_team_member(tmpdir, m3)
    
    members = list_team_members(tmpdir)
    test("名册有 3 个成员", len(members) == 3, f"got {len(members)}")
    test("成员包含 boss", any(m.name == "boss" for m in members))
    test("成员包含 worker-1", any(m.name == "worker-1" for m in members))
    test("成员包含 worker-2", any(m.name == "worker-2" for m in members))
    
    # 重名检测
    try:
        add_team_member(tmpdir, TeamMember(name="worker-1", role="worker"))
        test("重名检测", False, "should have raised ValueError")
    except ValueError:
        test("重名检测", True)
    
    # 移除成员
    remove_team_member(tmpdir, "worker-2")
    members = list_team_members(tmpdir)
    test("移除 worker-2 后剩 2 个", len(members) == 2, f"got {len(members)}")
    
    # 加回
    add_team_member(tmpdir, TeamMember(name="worker-2", role="worker", role_desc="Reviewer"))
    
    print()

    # ================================================================
    print("=== 2. 消息通道 (s15) ===")
    # ================================================================
    
    # Boss → worker-1 发消息
    send_to_teammate(tmpdir, "boss", "worker-1", "请帮我写一个 hello.py", "direct_message")
    send_to_teammate(tmpdir, "boss", "worker-1", "记得加上类型提示", "direct_message")
    
    count = peek_teammate_inbox(tmpdir, "worker-1")
    test("worker-1 inbox 有 2 条消息", count == 2, f"got {count}")
    
    # 排空 inbox
    msgs = drain_teammate_inbox(tmpdir, "worker-1")
    test("排空得到 2 条消息", len(msgs) == 2, f"got {len(msgs)}")
    test("第一条消息内容正确", "hello.py" in msgs[0]["content"])
    
    # 排空后应该为空
    count2 = peek_teammate_inbox(tmpdir, "worker-1")
    test("排空后 inbox 为空", count2 == 0, f"got {count2}")
    
    # worker-1 → boss 回复
    send_to_teammate(tmpdir, "worker-1", "boss", "hello.py 已完成！", "direct_message")
    boss_msgs = drain_teammate_inbox(tmpdir, "boss")
    test("Boss 收到 worker-1 回复", len(boss_msgs) == 1 and "完成" in boss_msgs[0]["content"])
    
    # 不存在的队友 inbox 为空
    empty = drain_teammate_inbox(tmpdir, "nonexistent")
    test("不存在队友的 inbox 为空", len(empty) == 0)
    
    print()

    # ================================================================
    print("=== 3. 工作图 + 原子认领 (s12/s15) ===")
    # ================================================================
    
    # 创建有依赖的任务链: task_a → task_b → task_c
    task_a = create_task(tmpdir, "A: 初始化项目结构")
    task_b = create_task(tmpdir, "B: 编写核心模块", blocked_by=[task_a.id])
    task_c = create_task(tmpdir, "C: 编写测试", blocked_by=[task_b.id])
    
    test("task_a 可执行", is_ready(task_a, tmpdir))
    test("task_b 被阻塞", not is_ready(task_b, tmpdir))
    test("task_c 被阻塞", not is_ready(task_c, tmpdir))
    
    # worker-1 认领 task_a
    claimed = claim_task(tmpdir, task_a.id, "worker-1", "worker")
    test("worker-1 认领 task_a 成功", claimed is not None)
    test("task_a 状态变为 in_progress", claimed.status == "in_progress")
    test("task_a owner 是 worker-1", claimed.owner == "worker-1")
    
    # 重复认领应该失败
    claimed2 = claim_task(tmpdir, task_a.id, "worker-2", "worker")
    test("重复认领失败", claimed2 is None)
    
    # 完成 task_a → 解锁 task_b
    complete_task(tmpdir, task_a.id, "项目结构已创建")
    
    task_b_reloaded = load_task(tmpdir, task_b.id)
    test("task_b 已解锁", is_ready(task_b_reloaded, tmpdir))
    
    # worker-2 认领 task_b
    claimed_b = claim_task(tmpdir, task_b.id, "worker-2", "worker")
    test("worker-2 认领 task_b 成功", claimed_b is not None)
    
    # 完成 task_b → 解锁 task_c
    complete_task(tmpdir, task_b.id, "核心模块已编写")
    task_c_reloaded = load_task(tmpdir, task_c.id)
    test("task_c 已解锁", is_ready(task_c_reloaded, tmpdir))
    
    # is_claimable 测试
    test("task_c 可被认领", is_claimable(task_c_reloaded, tmpdir, "worker"))
    
    print()

    # ================================================================
    print("=== 4. 结构化协议 (s16) ===")
    # ================================================================
    
    # 任务分配协议
    protocol, record = create_task_assign_protocol(
        tmpdir, "boss", "worker-1", task_c.id, task_c.subject
    )
    test("任务分配协议创建成功", record.request_id.startswith("req_"))
    test("协议状态 pending", record.status == "pending")
    test("worker-1 inbox 收到协议消息", peek_teammate_inbox(tmpdir, "worker-1") > 0)
    
    # 排空 worker-1 的协议消息
    proto_msgs = drain_teammate_inbox(tmpdir, "worker-1")
    proto_content = proto_msgs[0]["content"]
    test("协议消息类型是 protocol", proto_msgs[0]["msg_type"] == "protocol")
    test("协议内容包含 task_assign", "task_assign" in proto_content)
    
    # 关机协议
    shutdown_protocol, shutdown_record = create_shutdown_protocol(
        tmpdir, "boss", "worker-2", "测试结束，请关闭"
    )
    test("关机协议创建成功", shutdown_record.kind == "shutdown")
    
    # 审批协议
    plan_protocol, plan_record = create_plan_approval_protocol(
        tmpdir, "worker-1", "boss", "计划：重构 tools.py"
    )
    test("计划审批协议创建成功", plan_record.kind == "plan_approval")
    
    # Boss 审批通过
    resolved = resolve_request(tmpdir, plan_record.request_id, "approved", "看起来不错")
    test("审批通过", resolved.status == "approved")
    test("worker-1 收到审批结果", peek_teammate_inbox(tmpdir, "worker-1") > 0)
    
    # 列出所有请求
    all_requests = list_requests(tmpdir)
    test("共有 3 个请求记录", len(all_requests) == 3, f"got {len(all_requests)}")
    
    pending_requests = list_requests(tmpdir, "pending")
    test("还有 2 个 pending 请求", len(pending_requests) == 2, f"got {len(pending_requests)}")
    
    print()

    # ================================================================
    print("=== 5. 端到端模拟 ===")
    # ================================================================
    
    # 模拟完整的 Boss → Worker 协作流程
    # 1. Boss 创建任务
    t = create_task(tmpdir, "修复 login.py 的 bug")
    
    # 2. Boss 通过协议分配给 worker-1
    p, r = create_task_assign_protocol(tmpdir, "boss", "worker-1", t.id, t.subject)
    
    # 3. worker-1 收到消息
    msgs = drain_teammate_inbox(tmpdir, "worker-1")
    test("worker-1 收到任务分配", len(msgs) >= 1)
    
    # 4. worker-1 认领任务
    claimed_task = claim_task(tmpdir, t.id, "worker-1", "worker")
    test("worker-1 认领成功", claimed_task is not None and claimed_task.owner == "worker-1")
    
    # 5. worker-1 完成任务
    complete_task(tmpdir, t.id, "Bug 已修复：添加了空值检查")
    
    # 6. worker-1 通知 Boss
    send_to_teammate(tmpdir, "worker-1", "boss", 
                     f"任务 {t.id} 已完成：Bug 已修复", "direct_message")
    
    # 7. Boss 收到通知
    boss_msgs = drain_teammate_inbox(tmpdir, "boss")
    test("Boss 收到完成通知", any("已完成" in m["content"] for m in boss_msgs))
    
    # 8. 验证最终状态
    final_task = load_task(tmpdir, t.id)
    test("任务最终状态是 done", final_task.status == "done")
    test("任务结果是 Bug 已修复", "Bug" in final_task.result)
    
    print()

    # ================================================================
    print("=== 6. 工具注册验证 ===")
    # ================================================================
    
    from tools import get_tool_schemas, execute_tool
    
    schemas = get_tool_schemas()
    tool_names = [s["name"] for s in schemas]
    
    team_tool_names = ["TeamSpawn", "TeamList", "TeamShutdown", "SendMessage", "Broadcast", "AssignTask"]
    for tn in team_tool_names:
        test(f"工具 {tn} 已注册", tn in tool_names)
    
    # 测试 TeamList 工具执行
    config = {"cwd": tmpdir}
    result = execute_tool("TeamList", {}, config)
    test("TeamList 工具可执行", "Team Members" in result or "No team members" in result, result[:100])
    
    # 测试 TaskList 工具
    result = execute_tool("TaskList", {}, config)
    test("TaskList 工具可执行", "task_" in result or "No tasks" in result)
    
    print()

finally:
    # 清理临时目录
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"🧹 已清理临时目录: {tmpdir}")

# ===== 结果 =====
print()
print("=" * 50)
print(f"  测试结果: {passed} passed, {failed} failed")
if failed == 0:
    print("  🎉 全部通过！多 Agent 架构工作正常。")
else:
    print(f"  ⚠ 有 {failed} 个测试失败")
print("=" * 50)
