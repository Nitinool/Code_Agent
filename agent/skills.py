# skills.py — Skill 加载器
# 扫描 skills/ 目录，支持命名空间（namespace/skill-name）。
# 解析 SKILL.md（YAML frontmatter + markdown body），
# 提供激活/停用/列表/注入功能。
#
# Skill 目录结构：
#   skills/
#     <namespace>/
#       <skill-name>/
#         SKILL.md          # 必需：YAML frontmatter + markdown 指令
#         supporting.md     # 可选：辅助文件
#
# 搜索路径（优先级从高到低）：
#   1. 项目级：<cwd>/skills/
#   2. 全局级：~/.my_agent/skills/

import os
import re
from pathlib import Path
from typing import Optional


# ===== 数据结构 =====

class Skill:
    """单个 skill 的元数据与内容"""
    def __init__(self, name: str, description: str, body: str, path: Path,
                 source: str, namespace: str = ""):
        self.name = name                    # 短名称，如 "brainstorming"
        self.full_name = f"{namespace}/{name}" if namespace else name  # 全限定名
        self.namespace = namespace          # 命名空间，如 "superpowers"
        self.description = description
        self.body = body                    # frontmatter 之后的 markdown 正文
        self.raw = ""                       # 完整原始内容（含 frontmatter）
        self.path = path                    # SKILL.md 所在目录
        self.source = source                # "project" | "global"


# ===== 全局状态 =====

_skills_cache: dict[str, Skill] = {}     # full_name → Skill
_namespaces: dict[str, list[str]] = {}   # namespace → [full_name, ...]
_cache_loaded = False


# ===== 简易 YAML frontmatter 解析（不依赖 PyYAML）=====

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def _parse_simple_yaml(text: str) -> dict:
    """
    解析极简 YAML frontmatter。
    支持：
      - key: value（单行）
      - key: "value" / key: 'value'（引号）
      - key: >（折叠块标量，后续缩进行用空格连接）
      - key: |（字面块标量，后续缩进行用换行连接）
      - 列表项（- item）
    不支持：深层嵌套、锚点、标签等高级特性。
    """
    result = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 跳过空行和注释
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # 列表项: - value
        if stripped.startswith("- "):
            # 简单收集到列表
            list_key = None
            for existing_key in result:
                if isinstance(result[existing_key], list):
                    list_key = existing_key
                    break
            if list_key is None:
                # 没有已有列表，跳过（我们不处理顶层列表）
                pass
            else:
                item = stripped[2:].strip().strip('"').strip("'")
                result[list_key].append(item)
            i += 1
            continue

        # 子列表项（缩进的 - item）
        if line.startswith("  - ") or line.startswith("    - "):
            item = stripped[1:].strip().strip('"').strip("'")
            # 找到最近的非列表 key，追加
            for existing_key in reversed(list(result.keys())):
                if isinstance(result[existing_key], list):
                    result[existing_key].append(item)
                    break
            i += 1
            continue

        # key: value 行
        if ":" in stripped:
            key, _, rest = stripped.partition(":")
            key = key.strip()
            rest = rest.strip()

            # 块标量: key: > 或 key: |
            if rest in (">", "|"):
                block_style = rest  # ">" = folded, "|" = literal
                # 收集后续缩进行
                i += 1
                block_lines = []
                # 确定基础缩进（下一行的前导空格数）
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.strip() == "":
                        # 空行：literal 保留，folded 也保留（作为段落分隔）
                        block_lines.append("")
                        i += 1
                        continue
                    # 检查是否有缩进（至少 2 空格）
                    if next_line.startswith("  ") or next_line.startswith("\t"):
                        block_lines.append(next_line.strip())
                        i += 1
                    else:
                        # 缩进结束
                        break

                if block_style == ">":
                    # 折叠：用空格连接，空行变成段落分隔
                    value = " ".join(block_lines)
                    # 合并多余空格
                    value = re.sub(r'\s+', ' ', value).strip()
                else:
                    # 字面：用换行连接
                    value = "\n".join(block_lines)
                result[key] = value
                continue

            # 普通值
            value = rest.strip().strip('"').strip("'")
            result[key] = value
        else:
            # 可能是列表值的一部分或缩进内容
            pass

        i += 1

    return result


def _parse_skill_file(filepath: Path, namespace: str = "") -> Optional[Skill]:
    """解析单个 SKILL.md 文件，返回 Skill 或 None"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None

    frontmatter = _parse_simple_yaml(m.group(1))

    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()
    if not name:
        return None

    body = content[m.end():]

    skill = Skill(
        name=name,
        description=description,
        body=body,
        path=filepath.parent,
        source="unknown",
        namespace=namespace,
    )
    skill.raw = content
    return skill


# ===== 扫描与加载 =====

def _get_search_dirs(cwd: str = None) -> list[tuple[Path, str]]:
    """返回 (路径, 来源标签) 列表"""
    dirs = []

    # 项目级
    project_dir = Path(cwd or os.getcwd()) / "skills"
    dirs.append((project_dir, "project"))

    # 全局级
    global_dir = Path.home() / ".my_agent" / "skills"
    dirs.append((global_dir, "global"))

    return dirs


def _scan_skills_dir(base_dir: Path, source: str, namespace: str = ""):
    """递归扫描 skills 目录，将找到的 skill 加入缓存"""
    if not base_dir.is_dir():
        return

    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue

        skill_file = entry / "SKILL.md"
        if skill_file.exists():
            # 这是一个 skill 目录
            skill = _parse_skill_file(skill_file, namespace)
            if skill:
                skill.source = source
                # 项目级覆盖全局级同名 skill
                if skill.full_name not in _skills_cache or source == "project":
                    _skills_cache[skill.full_name] = skill
                    # 注册到命名空间
                    if namespace:
                        _namespaces.setdefault(namespace, []).append(skill.full_name)
        else:
            # 可能是命名空间目录，递归扫描
            sub_namespace = f"{namespace}/{entry.name}" if namespace else entry.name
            _scan_skills_dir(entry, source, sub_namespace)


def load_skills(cwd: str = None, force: bool = False):
    """扫描所有 skill 目录，加载到缓存"""
    global _skills_cache, _namespaces, _cache_loaded
    if _cache_loaded and not force:
        return
    _skills_cache.clear()
    _namespaces.clear()

    for base_dir, source in _get_search_dirs(cwd):
        _scan_skills_dir(base_dir, source)

    _cache_loaded = True


def list_skills(cwd: str = None) -> list[dict]:
    """列出所有可用 skill（摘要信息）"""
    load_skills(cwd)
    result = []
    for full_name, skill in sorted(_skills_cache.items()):
        result.append({
            "name": skill.name,
            "full_name": full_name,
            "namespace": skill.namespace,
            "description": skill.description,
            "source": skill.source,
            "path": str(skill.path),
        })
    return result


def list_namespaces(cwd: str = None) -> list[dict]:
    """列出所有命名空间及其 skill 数量"""
    load_skills(cwd)
    result = []
    for ns, skill_names in sorted(_namespaces.items()):
        result.append({
            "namespace": ns,
            "skill_count": len(skill_names),
            "skills": skill_names,
        })
    return result


def get_skill(full_name: str, cwd: str = None) -> Optional[Skill]:
    """获取单个 skill（通过全限定名）"""
    load_skills(cwd)
    return _skills_cache.get(full_name)


def get_namespace_skills(namespace: str, cwd: str = None) -> list[str]:
    """获取命名空间下所有 skill 的全限定名"""
    load_skills(cwd)
    return _namespaces.get(namespace, [])


def get_active_skill_contents(active_names: list[str], cwd: str = None) -> str:
    """
    返回所有已激活 skill 的内容（拼接后的 markdown），用于注入 system prompt。
    支持命名空间通配符：如果 active_names 包含 "superpowers"，
    则展开为 superpowers 命名空间下的所有 skill。
    """
    load_skills(cwd)

    # 展开命名空间通配符
    expanded = []
    for name in active_names:
        if name in _namespaces:
            # 命名空间引用 → 展开为所有子 skill
            expanded.extend(_namespaces[name])
        else:
            expanded.append(name)

    parts = []
    for full_name in expanded:
        skill = _skills_cache.get(full_name)
        if skill is None:
            continue
        parts.append(f"\n\n<!-- SKILL: {skill.full_name} -->\n{skill.body}")
    return "".join(parts)


def resolve_skill_name(partial: str, cwd: str = None) -> Optional[str]:
    """
    模糊匹配 skill 名称，返回完整全限定名或 None。
    支持：
      - 精确匹配全限定名: "superpowers/brainstorming"
      - 精确匹配短名称: "brainstorming"（唯一时）
      - 前缀匹配: "brain"
      - 命名空间匹配: "superpowers"（返回命名空间名，由调用方处理）
    """
    load_skills(cwd)
    partial_lower = partial.lower()

    # 精确匹配全限定名
    if partial in _skills_cache:
        return partial

    # 精确匹配命名空间
    if partial in _namespaces:
        return partial  # 返回命名空间名，调用方需展开

    # 在短名称中搜索
    short_matches = []
    for full_name, skill in _skills_cache.items():
        if skill.name.lower() == partial_lower:
            short_matches.append(full_name)
    if len(short_matches) == 1:
        return short_matches[0]

    # 前缀匹配（在全限定名中）
    prefix_matches = [n for n in _skills_cache if n.lower().startswith(partial_lower)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    # 包含匹配（在全限定名中）
    contains_matches = [n for n in _skills_cache if partial_lower in n.lower()]
    if len(contains_matches) == 1:
        return contains_matches[0]

    # 包含匹配（在短名称中）
    short_contains = [fn for fn, s in _skills_cache.items() if partial_lower in s.name.lower()]
    if len(short_contains) == 1:
        return short_contains[0]

    return None
