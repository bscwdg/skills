#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_pack.py —— 读取 pack-plan.json，生成 Umi Claw 大肥鱼资料包（umi-character-pack/1）。

输入：pack-plan.json（persona 文本 / knowledge 条目 / topics 卡片 / lines 台词组 / memory 关系与日记）
输出：资料包目录（manifest.json + persona.json + proactive/ + knowledge/ + memory/）

用法：
    python build_pack.py <pack-plan.json> -o <输出目录> [--force]
                         [--keep-sensitive] [--strict-privacy]

设计要点：
- 先全部在内存里组装并校验上限/隐私，再落盘；中途失败不会留下半包。
- 自动补 AGENTS.md 边界硬段（与 electron/main/character/persona.ts 逐字一致）。
- 默认脱敏手机号/身份证/银行卡/邮箱/门牌地址；密钥/私钥/Token/明文密码直接拒绝。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pack_common import (  # noqa: E402
    AGENTS_BOUNDARY_END,
    AGENTS_BOUNDARY_START,
    KNOWLEDGE_CATEGORIES,
    LINE_GROUP_RE,
    MAX_FILE_BYTES,
    MAX_KNOWLEDGE_FILES,
    MAX_LINE_CHARS,
    MAX_LINE_GROUPS,
    MAX_LINES_PER_GROUP,
    MAX_RELATIONS,
    MAX_TOPICS,
    MEMORY_KINDS,
    PACK_MAX_BYTES,
    PERSONA_MAX_TOTAL_BYTES,
    PERSONA_SLOTS,
    SCHEMA,
    SEASONS,
    TARGETS,
    TOPIC_SLOTS,
    configure_stdout,
    decode_text,
    ensure_agents_boundary,
    human_size,
    is_valid_date,
    load_json_bytes,
    next_unique_name,
    redact_privacy,
    sanitize_file_name,
    scan_privacy,
    secret_kinds,
    strip_bom,
    strip_frontmatter,
    write_json,
    write_text,
)

DEFAULT_AGENTS_MD = """# AGENTS.md — 运行规则

## 说话
- 保持人格文件里确定的语气与称呼；称呼按宿主设置，不写死名字。
- 短句，动作写括号里；不要客服腔、不每句反问、不写小作文。

## 记忆与日记
- 记忆与日记由 Umi Claw 宿主管理，走 Obsidian「大肥鱼/」目录；不新建知识库，不编造共同经历。
"""

PLAN_KEYS = {
    "name",
    "source",
    "targets",
    "persona",
    "knowledge",
    "topics",
    "topicsVersion",
    "lines",
    "proactive",
    "memory",
}


class BuildError(Exception):
    """pack-plan 内容不满足契约（给出可直接执行的修复提示）。"""


class Context:
    def __init__(self, plan_dir: Path, keep_sensitive: bool, strict_privacy: bool) -> None:
        self.plan_dir = plan_dir
        self.keep_sensitive = keep_sensitive
        self.strict_privacy = strict_privacy
        self.warnings: list[str] = []
        self.masked: dict[str, int] = {}

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def read_value(self, value: object, where: str) -> str:
        """字符串直接返回；也接受 {"file": "相对 pack-plan 的路径"}，方便喂长文档。"""
        if isinstance(value, str):
            return strip_bom(value)
        if isinstance(value, dict) and isinstance(value.get("file"), str):
            rel = value["file"]
            target = (self.plan_dir / rel).resolve()
            try:
                target.relative_to(self.plan_dir.resolve())
            except ValueError as exc:
                raise BuildError(f"{where}: file 必须位于 pack-plan.json 同级或子目录内：{rel}") from exc
            if not target.is_file():
                raise BuildError(f"{where}: 找不到 file 指向的文件：{rel}")
            try:
                text, _ = decode_text(target.read_bytes(), rel)
            except ValueError as exc:
                raise BuildError(f"{where}: {exc}") from exc
            return text
        raise BuildError(f"{where}: 必须是字符串，或 {{\"file\": \"相对路径\"}}")

    def guard(self, text: str, where: str) -> str:
        """凭据硬错误 + 个人敏感信息默认脱敏。"""
        if "\u0000" in text:
            raise BuildError(f"{where}: 含 NUL 字符（契约禁止）")
        found = scan_privacy(text)
        if not found:
            return text
        secrets = secret_kinds(found)
        if secrets:
            raise BuildError(
                f"{where}: 检测到疑似凭据/明文密码（{'、'.join(secrets)}）。"
                "资料包不得包含密钥或密码，请删除该段后重跑。"
            )
        kinds = "、".join(f"{kind} {count} 处" for kind, count in found.items())
        if self.strict_privacy:
            raise BuildError(f"{where}: 检测到个人敏感信息（{kinds}）；--strict-privacy 下必须人工脱敏后重跑。")
        if self.keep_sensitive:
            self.warn(f"{where}: 含个人敏感信息（{kinds}），按 --keep-sensitive 保留未脱敏；请确认是虚构内容。")
            return text
        redacted = redact_privacy(text)
        for kind, count in found.items():
            self.masked[kind] = self.masked.get(kind, 0) + count
        self.warn(f"{where}: 已自动脱敏（{kinds}）；如确需保留请加 --keep-sensitive")
        return redacted


def _as_str(value: object, where: str, ctx: Context, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        ctx.warn(f"{where}: 应为字符串，已忽略（{type(value).__name__}）")
        return default
    return value.strip()


def _string_list(value: object, where: str, ctx: Context, *, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        ctx.warn(f"{where}: 应为字符串数组，已忽略")
        return []
    if len(value) > limit:
        ctx.warn(f"{where}: 超过 {limit} 条，已截断（应用侧也只取前 {limit} 条）")
    out: list[str] = []
    for index, item in enumerate(value[:limit]):
        if not isinstance(item, str):
            ctx.warn(f"{where}[{index}]: 不是字符串，已忽略")
            continue
        text = item.strip()
        if not text:
            continue
        if len(text) > MAX_LINE_CHARS:
            ctx.warn(f"{where}[{index}]: 超过 {MAX_LINE_CHARS} 字，已截断（应用侧同样截断）")
            text = text[:MAX_LINE_CHARS]
        out.append(ctx.guard(text, f"{where}[{index}]"))
    return out


def _enum_list(value: object, allowed: tuple[str, ...], where: str, ctx: Context) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        ctx.warn(f"{where}: 应为字符串数组，已忽略")
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            ctx.warn(f"{where}: 含非字符串项，已忽略")
            continue
        if item in allowed:
            if item not in out:
                out.append(item)
        else:
            ctx.warn(f"{where}: 未知取值 {item!r}（只允许 {'/'.join(allowed)}），已丢弃")
    return out


def build_persona(raw: object, ctx: Context, outputs: dict[str, str]) -> int:
    if not isinstance(raw, dict):
        raise BuildError("persona 必须是对象：{\"herName\": \"大肥鱼\", \"files\": {\"SOUL.md\": \"...\"}}")
    her_name = raw.get("herName") or "大肥鱼"
    if not isinstance(her_name, str) or not her_name.strip():
        raise BuildError("persona.herName 必须是非空字符串（默认「大肥鱼」）")
    raw_files = raw.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise BuildError("persona.files 必须是非空对象，键只能是 SOUL.md / IDENTITY.md / AGENTS.md / USER.md")
    slots: dict[str, str] = {}
    for slot in raw_files:
        if slot not in PERSONA_SLOTS:
            raise BuildError(
                f"persona.files 含未知槽位 {slot!r}；只允许 {' / '.join(PERSONA_SLOTS)}"
            )
    total = 0
    for slot in PERSONA_SLOTS:
        if slot not in raw_files:
            continue
        text = ctx.read_value(raw_files[slot], f"persona.files[{slot}]")
        if not text.strip():
            raise BuildError(f"persona.files[{slot}] 内容为空")
        text = ctx.guard(text, f"persona.files[{slot}]")
        if slot == "AGENTS.md":
            # 边界硬段必须存在且是 canonical 版本；应用导入时还会再规范化一次。
            if AGENTS_BOUNDARY_START not in text:
                ctx.warn("persona.files[AGENTS.md]: 已自动补 AGENTS.md 边界硬段（不假装人类 / 危机转介 / 不卖惨）")
            text = ensure_agents_boundary(text)
        if re.search(r"\{\{[^{}]+\}\}", text):
            ctx.warn(
                f"persona.files[{slot}]: 含 {{{{变量}}}} 占位符；导入应用时不会替换（只有内置模板会渲染变量），请改写成具体文字"
            )
        if "\u0000" in text:
            raise BuildError(f"persona.files[{slot}]: 含 NUL 字符")
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise BuildError(f"persona.files[{slot}]: {human_size(size)}，超过单文件 512KB 上限")
        total += size
        slots[slot] = text
    if "AGENTS.md" not in slots:
        ctx.warn(
            "persona 未提供 AGENTS.md：已自动生成最小运行规则并补边界硬段；"
            "若想保留应用里现有 AGENTS.md 的自定义规则，请把原规则并入 pack-plan 后重跑"
        )
        slots["AGENTS.md"] = ensure_agents_boundary(DEFAULT_AGENTS_MD)
        total += len(slots["AGENTS.md"].encode("utf-8"))
    if total > PERSONA_MAX_TOTAL_BYTES:
        raise BuildError(f"persona 总体积 {human_size(total)} 超过 2MB 上限")
    outputs["persona.json"] = json.dumps(
        {"version": 1, "herName": her_name.strip(), "exportedAt": int(datetime.now().timestamp() * 1000), "files": slots},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return len(slots)


def build_knowledge(raw: object, ctx: Context, outputs: dict[str, str]) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise BuildError("knowledge 必须是数组：[{\"category\": \"世界书\", \"name\": \"标题\", \"text\": \"...\"}]")
    if len(raw) > MAX_KNOWLEDGE_FILES:
        raise BuildError(f"knowledge 共 {len(raw)} 篇，超过 {MAX_KNOWLEDGE_FILES} 篇上限")
    counts: dict[str, int] = {}
    used: dict[str, set[str]] = {category: set() for category in KNOWLEDGE_CATEGORIES}
    seen_text: dict[str, set[str]] = {category: set() for category in KNOWLEDGE_CATEGORIES}
    for index, item in enumerate(raw):
        where = f"knowledge[{index}]"
        if not isinstance(item, dict):
            raise BuildError(f"{where}: 必须是对象")
        category = item.get("category")
        if not isinstance(category, str) or category not in KNOWLEDGE_CATEGORIES:
            raise BuildError(f"{where}.category 不支持：{category!r}；只允许 {' / '.join(KNOWLEDGE_CATEGORIES)}")
        raw_name = item.get("name", item.get("title"))
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise BuildError(f"{where}.name 必须是非空字符串（会成为笔记文件名）")
        text = ctx.read_value(item.get("text"), f"{where}.text")
        text = strip_frontmatter(text)
        if not text.strip():
            raise BuildError(f"{where}.text 内容为空")
        text = ctx.guard(text, f"{where}.text")
        normalized = re.sub(r"\s+", "", text)
        if normalized in seen_text[category]:
            ctx.warn(f"{where}: 与前面同类别条目内容重复，已去重丢弃（{raw_name}）")
            continue
        seen_text[category].add(normalized)
        safe = sanitize_file_name(raw_name)
        unique = next_unique_name(used[category], safe)
        if unique != safe:
            ctx.warn(f"{where}: 同类别已有同名文件，已改名 {safe} → {unique}")
        used[category].add(unique)
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise BuildError(f"{where}: {human_size(size)}，超过单篇 512KB 上限")
        rel = f"knowledge/{category}/{unique}"
        outputs[rel] = text if text.endswith("\n") else text + "\n"
        counts[category] = counts.get(category, 0) + 1
    if sum(counts.values()) > MAX_KNOWLEDGE_FILES:
        raise BuildError(f"知识条目超过 {MAX_KNOWLEDGE_FILES} 篇上限")
    return counts


def build_topics(raw: object, version: object, ctx: Context, outputs: dict[str, str]) -> int:
    """返回话题卡张数；没有话题返回 0。"""
    if raw is None:
        return 0
    topics_version = "1.0.0"
    if isinstance(raw, dict):
        topics_version = _as_str(raw.get("version"), "topics.version", ctx, default="1.0.0") or "1.0.0"
        cards = raw.get("topics")
    else:
        cards = raw
        if isinstance(version, str) and version.strip():
            topics_version = version.strip()
    if not isinstance(cards, list):
        raise BuildError("topics 必须是数组，或 {\"version\": \"1.0.0\", \"topics\": [...]}")
    if len(cards) > MAX_TOPICS:
        raise BuildError(f"话题卡 {len(cards)} 张，超过 {MAX_TOPICS} 张上限")
    built: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, raw_card in enumerate(cards):
        where = f"topics[{index}]"
        if not isinstance(raw_card, dict):
            raise BuildError(f"{where}: 必须是对象")
        topic_id = raw_card.get("id")
        if not isinstance(topic_id, str) or not topic_id.strip():
            raise BuildError(f"{where}.id 必须是非空字符串")
        topic_id = topic_id.strip()
        if topic_id in seen_ids:
            raise BuildError(f"{where}.id 重复：{topic_id}（话题卡 id 必须唯一，应用侧按 id 覆盖）")
        seen_ids.add(topic_id)
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", topic_id):
            ctx.warn(f"{where}.id 含非常规字符（{topic_id}）；建议只用小写字母/数字/短横线，便于日志排查")
        title = _as_str(raw_card.get("title"), f"{where}.title", ctx, default=topic_id) or topic_id
        when = _as_str(raw_card.get("when"), f"{where}.when", ctx)
        stance = _as_str(raw_card.get("stance"), f"{where}.stance", ctx)
        details = _string_list(raw_card.get("details"), f"{where}.details", ctx, limit=10)
        hooks = _string_list(raw_card.get("hooks"), f"{where}.hooks", ctx, limit=10)
        sample = _as_str(raw_card.get("sample"), f"{where}.sample", ctx)
        if sample:
            sample = ctx.guard(sample, f"{where}.sample")
        if not sample and not hooks:
            raise BuildError(f"{where}: 每张话题卡必须有 sample 或 hooks 至少一个（应用侧会丢弃空卡）")
        requires = raw_card.get("requiresChatMention", False)
        if not isinstance(requires, bool):
            ctx.warn(f"{where}.requiresChatMention 应为布尔值，已按 false 处理")
            requires = False
        slots = _enum_list(raw_card.get("slots"), TOPIC_SLOTS, f"{where}.slots", ctx)
        seasons = _enum_list(raw_card.get("seasons"), SEASONS, f"{where}.seasons", ctx)
        built.append(
            {
                "id": topic_id,
                "title": title,
                "when": when,
                "stance": stance,
                "details": details,
                "hooks": hooks,
                "sample": sample,
                "requiresChatMention": requires,
                "slots": slots,
                "seasons": seasons,
            }
        )
    outputs["proactive/topics.json"] = json.dumps(
        {"schema": "fish-topics/1", "version": topics_version, "topics": built},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return len(built)


def build_lines(raw: object, ctx: Context, outputs: dict[str, str]) -> tuple[int, int, int]:
    """返回 (组数, 总句数, 去重丢弃句数)。"""
    if raw is None:
        return 0, 0, 0
    if not isinstance(raw, dict):
        raise BuildError("lines 必须是对象：{\"greeting\": [\"...\"], ...}")
    version = "1.0.0"
    if isinstance(raw.get("groups"), dict):
        version = _as_str(raw.get("version"), "lines.version", ctx, default="1.0.0") or "1.0.0"
        groups_raw = raw["groups"]
    else:
        groups_raw = raw
    if not groups_raw:
        raise BuildError("lines 没有任何台词组")
    if len(groups_raw) > MAX_LINE_GROUPS:
        raise BuildError(f"台词组 {len(groups_raw)} 组，超过 {MAX_LINE_GROUPS} 组上限")
    groups: dict[str, list[str]] = {}
    dropped = 0
    for name, value in groups_raw.items():
        where = f"lines.{name}"
        if not isinstance(name, str) or not LINE_GROUP_RE.match(name):
            raise BuildError(
                f"台词组名 {name!r} 不合法：应用侧只接受 ^[a-z][a-z0-9-]{{0,31}}$（小写字母开头、小写字母/数字/短横线）"
            )
        if not isinstance(value, list) or not value:
            raise BuildError(f"{where}: 必须是非空字符串数组")
        lines: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, str):
                ctx.warn(f"{where}[{index}]: 不是字符串，已忽略")
                continue
            text = item.strip()
            if not text:
                continue
            if len(text) > MAX_LINE_CHARS:
                ctx.warn(f"{where}[{index}]: 超过 {MAX_LINE_CHARS} 字，已截断（应用侧同样截断）")
                text = text[:MAX_LINE_CHARS]
            text = ctx.guard(text, f"{where}[{index}]")
            if text in seen:
                dropped += 1
                continue
            seen.add(text)
            lines.append(text)
            if len(lines) >= MAX_LINES_PER_GROUP:
                if index + 1 < len(value):
                    ctx.warn(f"{where}: 超过 {MAX_LINES_PER_GROUP} 句，多余已丢弃（应用侧同样只取前 {MAX_LINES_PER_GROUP} 句）")
                break
        if not lines:
            ctx.warn(f"{where}: 清洗后为空，已丢弃该组")
            continue
        groups[name] = lines
    if not groups:
        raise BuildError("lines 清洗后没有任何可用台词组")
    outputs["proactive/lines.json"] = json.dumps(
        {"schema": "fish-lines/1", "version": version, "groups": groups},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return len(groups), sum(len(lines) for lines in groups.values()), dropped


def build_memory(raw: object, ctx: Context, outputs: dict[str, str]) -> tuple[int, int]:
    if raw is None:
        return 0, 0
    if not isinstance(raw, dict):
        raise BuildError("memory 必须是对象：{\"relations\": [...], \"diaries\": [...]}")
    relations_raw = raw.get("relations") or []
    diaries_raw = raw.get("diaries") or []
    if not isinstance(relations_raw, list) or not isinstance(diaries_raw, list):
        raise BuildError("memory.relations / memory.diaries 必须是数组")
    if len(relations_raw) > MAX_RELATIONS:
        raise BuildError(f"memory.relations 共 {len(relations_raw)} 篇，超过 {MAX_RELATIONS} 篇上限")
    used: dict[str, set[str]] = {kind: set() for kind in MEMORY_KINDS}
    seen_text: set[str] = set()
    relation_count = 0
    for index, item in enumerate(relations_raw):
        where = f"memory.relations[{index}]"
        if not isinstance(item, dict):
            raise BuildError(f"{where}: 必须是对象")
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in MEMORY_KINDS:
            raise BuildError(f"{where}.kind 不支持：{kind!r}；只允许 {' / '.join(MEMORY_KINDS)}")
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise BuildError(f"{where}.name 必须是非空字符串（会成为笔记文件名）")
        text = strip_frontmatter(ctx.read_value(item.get("text"), f"{where}.text"))
        if not text.strip():
            raise BuildError(f"{where}.text 内容为空")
        text = ctx.guard(text, f"{where}.text")
        normalized = re.sub(r"\s+", "", text)
        if normalized in seen_text:
            ctx.warn(f"{where}: 与前面关系条目内容重复，已去重丢弃（{raw_name}）")
            continue
        seen_text.add(normalized)
        safe = sanitize_file_name(raw_name)
        unique = next_unique_name(used[kind], safe)
        if unique != safe:
            ctx.warn(f"{where}: 同名文件已存在，已改名 {safe} → {unique}")
        used[kind].add(unique)
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise BuildError(f"{where}: {human_size(size)}，超过单篇 512KB 上限")
        outputs[f"memory/relations/{kind}/{unique}"] = text if text.endswith("\n") else text + "\n"
        relation_count += 1

    diaries: dict[str, str] = {}
    for index, item in enumerate(diaries_raw):
        where = f"memory.diaries[{index}]"
        if not isinstance(item, dict):
            raise BuildError(f"{where}: 必须是对象")
        day = item.get("date")
        if not is_valid_date(day):
            raise BuildError(f"{where}.date 不合法：{day!r}；必须是真实日期 YYYY-MM-DD（如 2024-03-01）")
        text = strip_bom(ctx.read_value(item.get("text"), f"{where}.text"))
        if not text.strip():
            raise BuildError(f"{where}.text 内容为空")
        text = ctx.guard(text, f"{where}.text")
        if len(text) > 20000:
            ctx.warn(f"{where}: 超过 20000 字（应用侧日记编辑上限），导入后可能不方便再编辑")
        if day in diaries:
            ctx.warn(f"{where}: 日期 {day} 重复，已合并到同一篇日记")
            diaries[day] = diaries[day].rstrip() + "\n\n" + text.strip()
        else:
            diaries[day] = text if text.endswith("\n") else text + "\n"
        size = len(diaries[day].encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise BuildError(f"{where}: 合并后超过单篇 512KB 上限（{day}）")
    for day, text in diaries.items():
        outputs[f"memory/diaries/{day}.md"] = text
    return relation_count, len(diaries)


def build(plan_path: Path, out_dir: Path, *, force: bool, keep_sensitive: bool, strict_privacy: bool) -> int:
    try:
        plan = load_json_bytes(plan_path.read_bytes(), plan_path.name)
    except ValueError as exc:
        raise BuildError(str(exc)) from exc
    if not isinstance(plan, dict):
        raise BuildError("pack-plan.json 顶层必须是对象")
    ctx = Context(plan_path.resolve().parent, keep_sensitive, strict_privacy)
    for key in plan:
        if key not in PLAN_KEYS:
            ctx.warn(f"pack-plan 含未知字段 {key!r}，已忽略")

    name = plan.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise BuildError("name 必须是非空字符串")
    pack_name = name.strip() if isinstance(name, str) and name.strip() else out_dir.name
    source = plan.get("source")
    if source is not None and not isinstance(source, str):
        raise BuildError("source 必须是字符串（可省略）")

    outputs: dict[str, str] = {}
    proactive_raw = plan.get("proactive")
    if proactive_raw is not None and not isinstance(proactive_raw, dict):
        raise BuildError("proactive 必须是对象：{\"topics\": [...], \"lines\": {...}}")
    proactive = proactive_raw or {}

    persona_slots = 0
    if plan.get("persona") is not None:
        persona_slots = build_persona(plan["persona"], ctx, outputs)
    knowledge_counts = build_knowledge(plan.get("knowledge"), ctx, outputs)
    topic_count = build_topics(
        plan.get("topics", proactive.get("topics")),
        plan.get("topicsVersion"),
        ctx,
        outputs,
    )
    group_count, line_count, lines_dropped = build_lines(plan.get("lines", proactive.get("lines")), ctx, outputs)
    relation_count, diary_count = build_memory(plan.get("memory"), ctx, outputs)

    present: set[str] = set()
    if persona_slots:
        present.add("persona")
    if knowledge_counts:
        present.add("knowledge")
    if topic_count or group_count:
        present.add("proactive")
    if relation_count or diary_count:
        present.add("memory")
    targets = [target for target in TARGETS if target in present]
    if not targets:
        raise BuildError("pack-plan 没有产生任何内容：至少要有 persona / knowledge / topics+lines / memory 之一")
    declared_targets = plan.get("targets")
    if declared_targets is not None:
        if not isinstance(declared_targets, list):
            raise BuildError("targets 必须是数组")
        unknown = [item for item in declared_targets if item not in TARGETS]
        if unknown:
            raise BuildError(f"targets 含未知目标：{unknown}")
        if set(declared_targets) != set(targets):
            ctx.warn(f"pack-plan.targets 与实际内容不一致（实际：{', '.join(targets)}），已按实际内容生成 manifest")

    manifest = {
        "schema": SCHEMA,
        "name": pack_name,
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "targets": targets,
    }
    if isinstance(source, str) and source.strip():
        manifest["source"] = source.strip()
    outputs["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    total = sum(len(text.encode("utf-8")) for text in outputs.values())
    if total > PACK_MAX_BYTES:
        raise BuildError(f"整包体积 {human_size(total)} 超过 32MB 上限；请拆分或裁剪知识/台词")

    if out_dir.exists() and not out_dir.is_dir():
        raise BuildError(f"输出路径已存在且不是目录：{out_dir}")
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise BuildError(f"输出目录已存在且非空：{out_dir}；确认要覆盖请加 --force")

    tmp_dir = out_dir.parent / f".{out_dir.name}.tmp-{os.getpid()}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    try:
        for rel, text in outputs.items():
            write_text(tmp_dir / rel, text)
        if out_dir.exists():
            shutil.rmtree(out_dir)
        os.replace(tmp_dir, out_dir)
    except OSError as exc:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise BuildError(f"写入资料包失败：{exc}") from exc

    # ── 汇总输出 ──
    knowledge_total = sum(knowledge_counts.values())
    print(f"[完成] 资料包已生成：{out_dir}")
    print(f"  schema   : {SCHEMA}")
    print(f"  name     : {pack_name}")
    print(f"  targets  : {', '.join(targets)}")
    if persona_slots:
        print(f"  persona  : {persona_slots} 个槽位")
    if knowledge_total:
        detail = " / ".join(f"{category} {count}" for category, count in knowledge_counts.items())
        print(f"  knowledge: {knowledge_total} 篇（{detail}）")
    if topic_count or group_count:
        print(f"  proactive: 话题 {topic_count} 张 / 台词 {group_count} 组 {line_count} 句")
    if relation_count or diary_count:
        print(f"  memory   : 关系 {relation_count} 篇 / 日记 {diary_count} 天")
    print(f"  体积      : {human_size(total)} / 上限 32 MB")
    if ctx.masked:
        detail = "、".join(f"{kind} {count} 处" for kind, count in ctx.masked.items())
        print(f"  已脱敏    : {detail}")
    print(f"  警告      : {len(ctx.warnings)} 条")
    for warning in ctx.warnings[:40]:
        print(f"    - {warning}")
    if len(ctx.warnings) > 40:
        print(f"    … 其余 {len(ctx.warnings) - 40} 条省略")
    print()
    print(f"下一步：python validate_pack.py \"{out_dir}\"")
    print("提示：validate 全绿后再在 Umi Claw「大肥鱼 → 资料包」里导入，导入前应用会自动整包备份。")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="根据 pack-plan.json 生成 Umi Claw 大肥鱼资料包（umi-character-pack/1）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plan", help="pack-plan.json 路径")
    parser.add_argument("-o", "--out", required=True, help="输出资料包目录（已存在且非空需加 --force）")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的非空输出目录")
    parser.add_argument("--keep-sensitive", action="store_true", help="保留手机号/身份证/地址等敏感信息，不自动脱敏")
    parser.add_argument("--strict-privacy", action="store_true", help="发现个人敏感信息直接报错（不自动脱敏）")
    args = parser.parse_args(argv)

    plan_path = Path(args.plan)
    if not plan_path.is_file():
        print(f"[错误] pack-plan 不存在：{plan_path}", file=sys.stderr)
        return 1
    try:
        return build(
            plan_path,
            Path(args.out),
            force=args.force,
            keep_sensitive=args.keep_sensitive,
            strict_privacy=args.strict_privacy,
        )
    except BuildError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        print("[提示] pack-plan 的字段说明见 references/pack-format.md", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
