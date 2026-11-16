#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_pack.py —— 按「大肥鱼资料包契约 v1」（umi-character-pack/1）逐项校验。

校验对象可以是解压后的目录，也可以是 zip（zip 内单层顶层文件夹会自动识别）。

上限与应用侧对齐：整包 ≤32MB、条目总数 ≤2000（目录按文件数、zip 按压缩包条目数）、
manifest.json ≤256KB（专属上限）、其他单个 JSON ≤4MB、知识 ≤300 篇、话题 ≤200 张、台词组 ≤50 组、关系 ≤400 篇、单文件 ≤512KB。

用法：
    python validate_pack.py <资料包目录或 zip> [--strict-privacy] [--json]

退出码：0 = 合格（允许有警告）；1 = 不合格（有错误，应用侧导入会失败或丢内容）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pack_common import (  # noqa: E402
    DIARY_NAME_RE,
    KNOWLEDGE_CATEGORIES,
    LINE_GROUP_RE,
    MAX_FILE_BYTES,
    MAX_JSON_BYTES,
    MAX_KNOWLEDGE_FILES,
    MAX_LINE_CHARS,
    MAX_LINE_GROUPS,
    MAX_LINES_PER_GROUP,
    MAX_MANIFEST_BYTES,
    MAX_PACK_ENTRIES,
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
    agents_boundary_problems,
    configure_stdout,
    decode_text,
    human_size,
    is_text_path,
    is_valid_date,
    load_pack_files,
    PackLoadError,
    parse_iso8601,
    sanitize_file_name,
    scan_privacy,
    secret_kinds,
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict[str, object] = {}

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _load_json(report: Report, texts: dict[str, str], rel: str) -> object | None:
    raw = texts.get(rel)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        report.error(f"{rel}: 不是合法 JSON（{exc}）")
        return None


def check_manifest(report: Report, texts: dict[str, str]) -> dict | None:
    manifest = _load_json(report, texts, "manifest.json")
    if manifest is None:
        if "manifest.json" not in texts:
            report.error("缺少 manifest.json（资料包根目录必须有）")
        return None
    if not isinstance(manifest, dict):
        report.error("manifest.json: 顶层必须是对象")
        return None
    if manifest.get("schema") != SCHEMA:
        report.error(f"manifest.schema 必须是 {SCHEMA!r}，实际 {manifest.get('schema')!r}")
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        report.error("manifest.name 必须是非空字符串")
    created = manifest.get("createdAt")
    parsed = parse_iso8601(created)
    if parsed is None:
        report.error("manifest.createdAt 必须是 ISO8601 时间（如 2024-03-01T21:30:00+08:00）")
    elif "T" not in str(created) and " " not in str(created):
        report.warn("manifest.createdAt 只有日期没有时间，应用侧可能按 00:00 处理")
    source = manifest.get("source")
    if source is not None and not isinstance(source, str):
        report.error("manifest.source 必须是字符串（可省略）")
    targets = manifest.get("targets")
    if targets is not None:
        if not isinstance(targets, list):
            report.error("manifest.targets 必须是数组")
        else:
            unknown = [item for item in targets if item not in TARGETS]
            if unknown:
                report.error(f"manifest.targets 含未知目标：{unknown}（只允许 {list(TARGETS)}）")
            if len(set(targets)) != len(targets):
                report.warn("manifest.targets 有重复项")
    return manifest


def check_persona(report: Report, texts: dict[str, str]) -> dict[str, object] | None:
    pkg = _load_json(report, texts, "persona.json")
    if pkg is None:
        return None
    if not isinstance(pkg, dict):
        report.error("persona.json: 顶层必须是对象")
        return None
    if pkg.get("version") != 1:
        report.error(f"persona.version 必须是 1，实际 {pkg.get('version')!r}")
    her_name = pkg.get("herName")
    if not isinstance(her_name, str) or not her_name.strip():
        report.error("persona.herName 必须是非空字符串（应用侧约定「大肥鱼」）")
    elif her_name.strip() != "大肥鱼":
        report.warn(f"persona.herName = {her_name!r}；应用侧人格名固定为「大肥鱼」，此字段仅展示用")
    exported_at = pkg.get("exportedAt")
    if isinstance(exported_at, bool) or not isinstance(exported_at, int):
        report.error("persona.exportedAt 必须是毫秒时间戳（整数）")
    elif exported_at < 10**12:
        report.warn("persona.exportedAt 看起来是秒级时间戳，契约要求毫秒")
    files = pkg.get("files")
    if not isinstance(files, dict) or not files:
        report.error("persona.files 必须是非空对象（可只含部分槽位）")
        return None
    unknown = [slot for slot in files if slot not in PERSONA_SLOTS]
    if unknown:
        report.error(f"persona.files 含未知槽位：{unknown}（只允许 {list(PERSONA_SLOTS)}）")
    total = 0
    accepted = 0
    for slot in PERSONA_SLOTS:
        if slot not in files:
            continue
        value = files[slot]
        if not isinstance(value, str):
            report.error(f"persona.files[{slot}] 必须是字符串")
            continue
        accepted += 1
        if not value.strip():
            report.warn(f"persona.files[{slot}] 是空字符串（导入后该文件为空，建议删除该槽位）")
        if "\u0000" in value:
            report.error(f"persona.files[{slot}] 含 NUL 字符")
        size = len(value.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            report.error(f"persona.files[{slot}] {human_size(size)}，超过单文件 512KB 上限")
        total += size
        if re.search(r"\{\{[^{}]+\}\}", value):
            report.warn(f"persona.files[{slot}] 含 {{{{变量}}}} 占位符：应用导入不会替换（只有内置模板会渲染），语义可能不对")
        if slot == "AGENTS.md":
            for problem in agents_boundary_problems(value):
                report.error(f"persona.files[AGENTS.md] 边界硬段不完整：{problem}")
    if total > PERSONA_MAX_TOTAL_BYTES:
        report.error(f"persona 总体积 {human_size(total)}，超过 2MB 上限")
    if accepted == 0 and not unknown:
        report.error("persona.json 里没有任何可导入槽位")
    return {"slots": accepted, "bytes": total}


def check_topics(report: Report, texts: dict[str, str]) -> dict[str, object] | None:
    deck = _load_json(report, texts, "proactive/topics.json")
    if deck is None:
        return None
    if not isinstance(deck, dict):
        report.error("proactive/topics.json: 顶层必须是对象")
        return None
    if deck.get("schema") != "fish-topics/1":
        report.error(f"proactive/topics.json: schema 必须是 'fish-topics/1'，实际 {deck.get('schema')!r}")
    if not isinstance(deck.get("version"), str) or not deck["version"].strip():
        report.error("proactive/topics.json: version 必须是非空字符串（如 '1.0.0'）")
    topics = deck.get("topics")
    if not isinstance(topics, list):
        report.error("proactive/topics.json: topics 必须是数组")
        return None
    if len(topics) > MAX_TOPICS:
        report.error(f"话题卡 {len(topics)} 张，超过 {MAX_TOPICS} 张上限")
    seen: set[str] = set()
    for index, card in enumerate(topics):
        where = f"topics[{index}]"
        if not isinstance(card, dict):
            report.error(f"{where}: 必须是对象")
            continue
        topic_id = card.get("id")
        if not isinstance(topic_id, str) or not topic_id.strip():
            report.error(f"{where}.id 必须是非空字符串")
        else:
            topic_id = topic_id.strip()
            if topic_id in seen:
                report.warn(f"{where}.id 重复：{topic_id}（应用侧导入时警告并忽略后者，先出现的卡保留，不会按 id 覆盖）")
            seen.add(topic_id)
        for key in ("title", "when", "stance", "sample"):
            value = card.get(key)
            if value is not None and not isinstance(value, str):
                report.error(f"{where}.{key} 必须是字符串")
        sample = card.get("sample") if isinstance(card.get("sample"), str) else ""
        hooks = card.get("hooks")
        if hooks is not None and not isinstance(hooks, list):
            report.error(f"{where}.hooks 必须是数组")
            hooks = []
        hooks = hooks or []
        for key, limit in (("details", 10), ("hooks", 10)):
            value = card.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                report.error(f"{where}.{key} 必须是数组")
                continue
            if len(value) > limit:
                report.warn(f"{where}.{key} 有 {len(value)} 条，应用侧只取前 {limit} 条")
            for item_index, item in enumerate(value):
                if not isinstance(item, str):
                    report.warn(f"{where}.{key}[{item_index}] 不是字符串，应用侧会丢弃")
                elif len(item) > MAX_LINE_CHARS:
                    report.warn(f"{where}.{key}[{item_index}] 超过 {MAX_LINE_CHARS} 字，应用侧会截断")
        if not sample.strip() and not hooks:
            report.error(f"{where}: 每张卡必须有 sample 或 hooks 至少一个（应用侧会丢弃空卡）")
        requires = card.get("requiresChatMention")
        if requires is not None and not isinstance(requires, bool):
            report.error(f"{where}.requiresChatMention 必须是布尔值")
        for key, allowed in (("slots", TOPIC_SLOTS), ("seasons", SEASONS)):
            value = card.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                report.error(f"{where}.{key} 必须是数组")
                continue
            for item in value:
                if not isinstance(item, str):
                    report.error(f"{where}.{key} 含非字符串项")
                elif item not in allowed:
                    report.warn(f"{where}.{key} 含未知取值 {item!r}（允许 {list(allowed)}），应用侧会丢弃")
    return {"topics": len(topics)}


def check_lines(report: Report, texts: dict[str, str]) -> dict[str, object] | None:
    deck = _load_json(report, texts, "proactive/lines.json")
    if deck is None:
        return None
    if not isinstance(deck, dict):
        report.error("proactive/lines.json: 顶层必须是对象")
        return None
    if deck.get("schema") != "fish-lines/1":
        report.error(f"proactive/lines.json: schema 必须是 'fish-lines/1'，实际 {deck.get('schema')!r}")
    if not isinstance(deck.get("version"), str) or not deck["version"].strip():
        report.error("proactive/lines.json: version 必须是非空字符串（如 '1.0.0'）")
    groups = deck.get("groups")
    if not isinstance(groups, dict) or not groups:
        report.error("proactive/lines.json: groups 必须是非空对象")
        return None
    if len(groups) > MAX_LINE_GROUPS:
        report.error(f"台词组 {len(groups)} 组，超过 {MAX_LINE_GROUPS} 组上限")
    total_lines = 0
    for name, lines in groups.items():
        where = f"groups[{name}]"
        if not isinstance(name, str) or not LINE_GROUP_RE.match(name):
            report.error(f"{where}: 组名不合法，应用侧只接受 ^[a-z][a-z0-9-]{{0,31}}$")
            continue
        if not isinstance(lines, list) or not lines:
            report.error(f"{where}: 必须是非空字符串数组（应用侧会丢弃空组）")
            continue
        if len(lines) > MAX_LINES_PER_GROUP:
            report.warn(f"{where}: {len(lines)} 句，应用侧只取前 {MAX_LINES_PER_GROUP} 句")
        seen: set[str] = set()
        for index, line in enumerate(lines):
            if not isinstance(line, str):
                report.error(f"{where}[{index}]: 必须是字符串")
                continue
            if not line.strip():
                report.warn(f"{where}[{index}]: 空句子，应用侧会丢弃")
            if len(line) > MAX_LINE_CHARS:
                report.warn(f"{where}[{index}]: 超过 {MAX_LINE_CHARS} 字，应用侧会截断")
            if line in seen:
                report.warn(f"{where}[{index}]: 组内重复句子，应用侧合并时会去重")
            seen.add(line)
        total_lines += len(lines)
    return {"groups": len(groups), "lines": total_lines}


def _check_md_file(report: Report, files: dict[str, bytes], texts: dict[str, str], rel: str, label: str) -> bool:
    data = files[rel]
    size = len(data)
    if size > MAX_FILE_BYTES:
        report.error(f"{rel}: {human_size(size)}，超过单篇 512KB 上限")
    if "\u0000" in data.decode("utf-8", "ignore"):
        report.error(f"{rel}: 含 NUL 字符")
    text = texts.get(rel)
    if text is None:
        report.error(f"{rel}: 不是合法 UTF-8 文本")
        return False
    if not text.strip():
        report.warn(f"{rel}: {label}内容为空")
    return True


def check_knowledge(report: Report, files: dict[str, bytes], texts: dict[str, str]) -> dict[str, object] | None:
    unknown_dirs: set[str] = set()
    by_category: dict[str, int] = {}
    names: dict[str, set[str]] = {}
    contents: dict[str, set[str]] = {}
    count = 0
    for rel in sorted(files):
        if not rel.startswith("knowledge/"):
            continue
        inner = rel[len("knowledge/") :]
        category = None
        rest = inner
        for candidate in KNOWLEDGE_CATEGORIES:
            prefix = candidate + "/"
            if inner.startswith(prefix):
                category = candidate
                rest = inner[len(prefix) :]
                break
        if category is None:
            first = inner.split("/", 1)[0]
            if first and first not in unknown_dirs:
                unknown_dirs.add(first)
                report.warn(f"knowledge/{first}/: 未知知识类别，应用侧会忽略（允许：{list(KNOWLEDGE_CATEGORIES)}）")
            continue
        if not rest:
            continue
        basename = rest.rsplit("/", 1)[-1]
        if not basename.lower().endswith(".md"):
            report.warn(f"{rel}: 不是 .md 文件，应用侧会忽略")
            continue
        safe = sanitize_file_name(basename)
        if safe != basename:
            report.error(f"{rel}: 文件名不符合应用侧消毒规则，会被改名；建议直接改成 {safe}")
        if not _check_md_file(report, files, texts, rel, "知识"):
            continue
        text = texts.get(rel, "")
        normalized = re.sub(r"\s+", "", text)
        if normalized:
            bucket = contents.setdefault(category, set())
            if normalized in bucket:
                report.warn(f"{rel}: 与同类别另一篇内容重复，建议去重")
            bucket.add(normalized)
        bucket_names = names.setdefault(category, set())
        if basename in bucket_names:
            report.warn(f"{rel}: 同类别的嵌套目录里有同名文件，应用侧会加序号避免覆盖")
        bucket_names.add(basename)
        by_category[category] = by_category.get(category, 0) + 1
        count += 1
    if count > MAX_KNOWLEDGE_FILES:
        report.error(f"知识文件 {count} 篇，超过 {MAX_KNOWLEDGE_FILES} 篇上限")
    if count:
        return {"files": count, "by_category": by_category}
    return None


def check_memory(report: Report, files: dict[str, bytes], texts: dict[str, str]) -> dict[str, object] | None:
    relations = 0
    diaries = 0
    for rel in sorted(files):
        if rel.startswith("memory/relations/"):
            inner = rel[len("memory/relations/") :]
            parts = inner.split("/")
            if len(parts) < 2 or not parts[-1]:
                report.warn(f"{rel}: 关系笔记必须放在 memory/relations/<约定|大事记>/ 下")
                continue
            kind = parts[0]
            if kind not in MEMORY_KINDS:
                report.warn(f"memory/relations/{kind}/: 未知关系类别，应用侧会忽略（允许：{list(MEMORY_KINDS)}）")
                continue
            basename = parts[-1]
            if not basename.lower().endswith(".md"):
                report.warn(f"{rel}: 不是 .md 文件，应用侧会忽略")
                continue
            safe = sanitize_file_name(basename)
            if safe != basename:
                report.error(f"{rel}: 文件名不符合应用侧消毒规则，会被改名；建议直接改成 {safe}")
            if _check_md_file(report, files, texts, rel, "关系"):
                relations += 1
        elif rel.startswith("memory/diaries/"):
            inner = rel[len("memory/diaries/") :]
            if "/" in inner:
                report.error(f"{rel}: 日记必须直接放在 memory/diaries/ 下，不能再套子目录")
                continue
            match = DIARY_NAME_RE.match(inner)
            if not match:
                report.error(f"{rel}: 日记文件名必须是 YYYY-MM-DD.md")
                continue
            if not is_valid_date(match.group(1)):
                report.error(f"{rel}: 不是真实日期（拒绝 2026-02-30 这类）")
                continue
            if _check_md_file(report, files, texts, rel, "日记"):
                text = texts.get(rel, "")
                if len(text) > 20000:
                    report.warn(f"{rel}: {len(text)} 字，超过应用侧日记编辑上限 20000 字")
                diaries += 1
        elif rel.startswith("memory/"):
            report.warn(f"{rel}: 未识别的 memory 路径，应用侧会忽略")
    if relations > MAX_RELATIONS:
        report.error(f"关系笔记 {relations} 篇，超过 {MAX_RELATIONS} 篇上限")
    if relations or diaries:
        return {"relations": relations, "diaries": diaries}
    return None


def _entry_total(pack_path: Path, files: dict[str, bytes]) -> int:
    """条目总数：目录按文件数；zip 按压缩包条目数（含目录项，与应用侧上限口径一致）。"""
    if pack_path.is_file() and zipfile.is_zipfile(pack_path):
        try:
            with zipfile.ZipFile(pack_path) as archive:
                return len(archive.infolist())
        except (zipfile.BadZipFile, OSError):
            pass
    return len(files)


def validate(pack_path: Path, strict_privacy: bool = False) -> Report:
    report = Report()
    try:
        files, load_warnings = load_pack_files(pack_path)
    except PackLoadError as exc:
        report.error(str(exc))
        return report
    report.warnings.extend(load_warnings)

    texts: dict[str, str] = {}
    for rel, data in sorted(files.items()):
        if b"\x00" in data:
            report.error(f"{rel}: 含 NUL 字符（契约禁止）")
        json_limit = MAX_MANIFEST_BYTES if rel == "manifest.json" else MAX_JSON_BYTES
        if rel.lower().endswith(".json") and len(data) > json_limit:
            limit_label = "manifest.json 256KB" if rel == "manifest.json" else "单个 JSON 4MB"
            report.error(f"{rel}: {human_size(len(data))}，超过 {limit_label} 上限")
        if is_text_path(rel):
            try:
                texts[rel], _ = decode_text(data, rel)
            except ValueError as exc:
                report.error(str(exc))
        elif rel.startswith(("knowledge/", "proactive/", "memory/")):
            report.warn(f"{rel}: 不是 .md/.json 文本文件，应用侧会忽略")

    for rel in sorted(files):
        if rel in ("manifest.json", "persona.json"):
            continue
        if rel.startswith(("knowledge/", "proactive/", "memory/")):
            continue
        report.warn(f"未识别的文件（应用侧会忽略）：{rel}")
    for rel in sorted(files):
        if rel.startswith("proactive/") and rel not in ("proactive/topics.json", "proactive/lines.json"):
            report.warn(f"{rel}: proactive/ 下只识别 topics.json 与 lines.json")

    total_bytes = sum(len(data) for data in files.values())
    entry_total = _entry_total(pack_path, files)
    if total_bytes > PACK_MAX_BYTES:
        report.error(f"整包体积 {human_size(total_bytes)}，超过 32MB 上限")
    if entry_total > MAX_PACK_ENTRIES:
        report.error(
            f"条目总数 {entry_total}，超过 {MAX_PACK_ENTRIES} 上限"
            "（目录按文件数、zip 按压缩包条目数计，含目录项）"
        )

    for rel, text in sorted(texts.items()):
        found = scan_privacy(text)
        if not found:
            continue
        secrets = secret_kinds(found)
        if secrets:
            report.error(
                f"{rel}: 含疑似凭据/明文密码（{'、'.join(secrets)}）；资料包不得包含密钥或密码"
            )
        sensitive = [kind for kind in found if kind not in secrets]
        if sensitive:
            detail = "、".join(f"{kind} {found[kind]} 处" for kind in sensitive)
            if strict_privacy:
                report.error(f"{rel}: 含个人敏感信息（{detail}）；--strict-privacy 下不允许")
            else:
                report.warn(f"{rel}: 含个人敏感信息（{detail}）；建议删除或脱敏（build_pack.py 默认会自动脱敏）")

    manifest = check_manifest(report, texts)
    stats: dict[str, object] = {
        "bytes": total_bytes,
        "file_count": len(files),
        "entries": entry_total,
    }
    persona_stats = check_persona(report, texts)
    if persona_stats:
        stats["persona"] = persona_stats
    topics_stats = check_topics(report, texts)
    if topics_stats:
        stats["topics"] = topics_stats
    lines_stats = check_lines(report, texts)
    if lines_stats:
        stats["lines"] = lines_stats
    knowledge_stats = check_knowledge(report, files, texts)
    if knowledge_stats:
        stats["knowledge"] = knowledge_stats
    memory_stats = check_memory(report, files, texts)
    if memory_stats:
        stats["memory"] = memory_stats
    report.stats = stats

    present = set()
    if persona_stats:
        present.add("persona")
    if knowledge_stats:
        present.add("knowledge")
    if topics_stats or lines_stats:
        present.add("proactive")
    if memory_stats:
        present.add("memory")
    if not present:
        report.error("资料包里没有任何可导入内容（persona / knowledge / proactive / memory 全空）")
    if manifest and isinstance(manifest.get("targets"), list):
        declared = {item for item in manifest["targets"] if isinstance(item, str)}
        if declared != present:
            report.warn(f"manifest.targets 声明为 {sorted(declared)}，实际内容为 {sorted(present)}")
    return report


def _print_human(report: Report, pack_path: Path) -> None:
    stats = report.stats
    if report.errors:
        print(f"[失败] 资料包不符合 {SCHEMA}：{pack_path}")
        print(f"  错误 {len(report.errors)} 条：")
        for index, message in enumerate(report.errors, 1):
            print(f"   {index}. {message}")
    else:
        print(f"[通过] 资料包符合 {SCHEMA}：{pack_path}")
    print(
        "  统计: 体积 {size} / 上限 32MB；文件 {count} 个，条目 {entries} / 上限 2000".format(
            size=human_size(int(stats.get("bytes", 0))),
            count=stats.get("file_count", 0),
            entries=stats.get("entries", 0),
        )
    )
    if stats.get("persona"):
        print(f"  人格: {stats['persona'].get('slots', 0)} 个槽位")
    if stats.get("knowledge"):
        by_category = stats["knowledge"].get("by_category", {})
        detail = " / ".join(f"{category} {count}" for category, count in by_category.items())
        print(f"  知识: {stats['knowledge'].get('files', 0)} 篇（{detail}）")
    if stats.get("topics"):
        print(f"  话题: {stats['topics'].get('topics', 0)} 张")
    if stats.get("lines"):
        print(f"  台词: {stats['lines'].get('groups', 0)} 组 {stats['lines'].get('lines', 0)} 句")
    if stats.get("memory"):
        print(f"  记忆: 关系 {stats['memory'].get('relations', 0)} 篇 / 日记 {stats['memory'].get('diaries', 0)} 天")
    if report.warnings:
        print(f"  警告 {len(report.warnings)} 条（不影响导入）：")
        for index, message in enumerate(report.warnings, 1):
            print(f"   {index}. {message}")
    if not report.errors:
        print()
        print("下一步：在 Umi Claw「大肥鱼 → 资料包」里导入该目录（或先打 zip）；导入前应用会自动整包备份。")


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="校验 Umi Claw 大肥鱼资料包（umi-character-pack/1）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pack", help="资料包目录，或资料包 zip")
    parser.add_argument("--strict-privacy", action="store_true", help="发现个人敏感信息（手机号/身份证等）直接判不合格")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果（供 agent 解析）")
    args = parser.parse_args(argv)

    pack_path = Path(args.pack)
    if not pack_path.exists():
        print(f"[错误] 路径不存在：{pack_path}", file=sys.stderr)
        return 1
    report = validate(pack_path, strict_privacy=args.strict_privacy)
    if args.json:
        payload = {
            "ok": not report.errors,
            "schema": SCHEMA,
            "path": str(pack_path),
            "errors": report.errors,
            "warnings": report.warnings,
            "stats": report.stats,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(report, pack_path)
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
