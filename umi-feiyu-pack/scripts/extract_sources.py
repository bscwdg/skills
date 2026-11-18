#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_sources.py —— 把 txt/md/html/docx/pdf/角色卡 JSON/角色卡 PNG 提取成 sources/*.md + messages.jsonl + stats.json。

输入还支持其他 AI 角色应用导出的：
    *.json  Character Card V2/V3（{spec, spec_version, data}）或 V1 扁平卡 → 分段 Markdown
    *.json  World Info / Lorebook（entries / world_info）→ 每条一个二级标题；disable:true 跳过
    *.png   内嵌 chara / ccv3 文本块的 PNG 角色卡（标准库解析，不依赖 Pillow）
无法识别的 JSON 不当角色卡猜，也不静默当普通文本：原文保留到 sources 并给警告。

支持识别的聊天导出格式（同一文件里可混用）：
    2024-03-01 21:12:00 阿澈              ← 微信/QQ 常见：时间 + 昵称，正文在下一行起
    2024-03-01 21:12:00 阿澈(123456)      ← QQ：昵称后带 QQ 号
    2024-03-01 21:12:00 阿澈: 内容        ← 时间 + 昵称: 内容
    [2024-03-01 21:12:00] 阿澈: 内容      ← 带方括号
    阿澈 2024-03-01 21:12                 ← 昵称在前
    2024-03-01                            ← 只有日期的分组行，后接「昵称: 内容」

用法：
    python extract_sources.py <输入目录> [-o <输出目录>] [--no-recursive]

输出：
    <输出目录>/sources/*.md      每个输入文件一份纯文本/结构化提取结果
    <输出目录>/messages.jsonl    所有聊天文件的消息（ts / speaker / text）
    <输出目录>/stats.json        每个文件的提取统计与警告（files[].kind 标记 character-card / world-info / json-raw）

PDF 需要可选依赖 pypdf（或 pdfminer.six）；没装时不会静默失败，会给出替代方案并以退出码 1 结束。
"""

from __future__ import annotations

import argparse
import base64
import binascii
import html.parser
import io
import json
import os
import re
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pack_common import (  # noqa: E402
    JUNK_DIRS,
    JUNK_NAMES,
    configure_stdout,
    decode_text,
    human_size,
    next_unique_name,
    sanitize_file_name,
    write_json,
    write_text,
)

SUPPORTED_EXTS = {
    ".txt": "txt",
    ".text": "txt",
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".pdf": "pdf",
    # 角色卡/世界书都是 JSON；分开判定，不能一律当普通文本
    ".json": "json",
    # PNG 只在带 chara / ccv3 文本块时是角色卡，否则按普通图片跳过
    ".png": "png",
}

MAX_INPUT_BYTES = 64 * 1024 * 1024

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Character Card V2/V3 规范：SillyTavern 写 chara，V3 新卡写 ccv3（两份可能同时存在）
PNG_CARD_KEYWORDS = ("chara", "ccv3")
# 解压后的内嵌卡文本上限：和输入文件上限一致，避免 zlib 压缩炸弹把内存吃光
MAX_PNG_TEXT_BYTES = MAX_INPUT_BYTES

# 角色卡字段 → 中文小标题。顺序按用户阅读习惯排（名字/描述/性格/场景/开场/示例/备注），
# 其余字段统一落到「其他字段」，保证不丢字段。
CARD_SECTIONS = (
    ("name", "名字"),
    ("description", "描述"),
    ("personality", "性格"),
    ("scenario", "场景"),
    ("first_mes", "开场白"),
    ("mes_example", "示例对话"),
    ("creator_notes", "创作者备注"),
    ("system_prompt", "系统提示词"),
    ("post_history_instructions", "历史后置指令"),
    ("alternate_greetings", "备选开场白"),
)
CARD_META_KEYS = ("spec", "spec_version", "data")
CARD_FORMAT_LABELS = {
    "character-card-v1": "Character Card V1",
    "character-card-v2": "Character Card V2",
    "character-card-v3": "Character Card V3",
}


class PdfUnavailable(Exception):
    """没有可用的 PDF 解析库（不是文件损坏）。"""


def _iso_datetime(year: str, month: str, day: str, hour: str, minute: str, second: str | None) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"


def _iso_date(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


# ── 各格式提取 ──────────────────────────────────────────────────────────────


def extract_docx(data: bytes, where: str) -> str:
    """zipfile + xml.etree 解析 word/document.xml（不依赖 python-docx）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                xml_bytes = archive.read("word/document.xml")
            except KeyError as exc:
                raise ValueError(f"{where}: 不是有效的 .docx（缺少 word/document.xml）；旧版 .doc 请先另存为 .docx 或 .txt") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{where}: 不是有效的 .docx（zip 结构损坏）；旧版 .doc 请先另存为 .docx 或 .txt") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"{where}: word/document.xml 解析失败（{exc}）") from exc

    paragraph_tag = f"{{{W_NS}}}p"
    text_tag = f"{{{W_NS}}}t"
    tab_tag = f"{{{W_NS}}}tab"
    br_tag = f"{{{W_NS}}}br"
    cr_tag = f"{{{W_NS}}}cr"
    paragraphs: list[str] = []
    for paragraph in root.iter(paragraph_tag):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == text_tag and node.text:
                parts.append(node.text)
            elif node.tag == tab_tag:
                parts.append("\t")
            elif node.tag in (br_tag, cr_tag):
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


class _HtmlTextExtractor(html.parser.HTMLParser):
    BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "blockquote",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def extract_html(text: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(text)
    parser.close()
    raw = "".join(parser.parts)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in raw.split("\n")]
    out: list[str] = []
    for line in lines:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def extract_pdf(data: bytes, where: str) -> str:
    reader_cls = None
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader_cls = getattr(module, "PdfReader")
            break
        except (ImportError, AttributeError):
            continue
    if reader_cls is not None:
        try:
            reader = reader_cls(io.BytesIO(data))
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception as exc:  # noqa: BLE001 - 第三方库异常类型不稳定
                    raise ValueError(f"{where}: PDF 已加密，无法读取（{exc}）") from exc
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001
                    pages.append("")
            return "\n\n".join(pages)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{where}: PDF 解析失败（{exc}）；文件可能损坏或为扫描件") from exc

    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
    except ImportError:
        raise PdfUnavailable(where) from None
    try:
        return pdfminer_extract(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{where}: PDF 解析失败（{exc}）；文件可能损坏或为扫描件") from exc


# ── 角色卡 / 世界书（SillyTavern、Chub 等导出的 JSON 与 PNG）──────────────────


def _as_string_list(value: object) -> list[str]:
    """把 key / keysecondary 这类「字符串或字符串数组」统一成字符串列表。"""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item).strip()]
    return []


def _markdown_value(value: object) -> str:
    """角色卡字段渲染：字符串保留原文；列表/对象转 JSON，避免丢结构。"""
    if isinstance(value, str):
        return value if value.strip() else "（空）"
    if value is None:
        return "（空）"
    if isinstance(value, (int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    body = json.dumps(value, ensure_ascii=False, indent=2)
    # 值里可能含 ```，用足够长的围栏包住 JSON，避免把 Markdown 结构提前截断
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}json\n{body}\n{fence}"


def _looks_like_card_data(obj: object) -> bool:
    """V1 扁平卡 / V2 的 data 都要有 name，且至少两个专属字段，避免把普通配置 JSON 认成角色卡。"""
    if not isinstance(obj, dict):
        return False
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    signatures = ("description", "personality", "scenario", "first_mes", "mes_example")
    return sum(1 for key in signatures if key in obj) >= 2


def detect_character_card(root: object) -> tuple[dict[str, object], str, dict[str, object]] | None:
    """识别 Character Card V2/V3（{spec,data}）与 V1（扁平字段）。

    返回 (卡数据, 格式 id, 顶层额外字段)；识别不了返回 None。
    有 spec='chara_card_v*' 时以 spec 为准（规范强信号）；没有 spec 时必须结构像卡才认。
    """
    if not isinstance(root, dict):
        return None
    spec = root.get("spec")
    spec_lower = spec.strip().lower() if isinstance(spec, str) else ""
    version = root.get("spec_version")
    version_text = str(version).strip() if isinstance(version, (str, int, float)) else ""
    data = root.get("data")

    if isinstance(data, dict) and (spec_lower.startswith("chara_card") or _looks_like_card_data(data)):
        if spec_lower == "chara_card_v3" or version_text.startswith("3"):
            format_id = "character-card-v3"
        elif spec_lower == "chara_card_v2" or version_text.startswith("2"):
            format_id = "character-card-v2"
        else:
            # 没有 spec/spec_version 的嵌套卡最常见于 V2 导出；V1 没有 data 层
            format_id = "character-card-v2"
        # 顶层除 spec/spec_version/data 之外的字段（如 avatar）也保留，但和 data 同名的跳过，避免重复贴正文
        extras = {
            key: value
            for key, value in root.items()
            if key not in CARD_META_KEYS and key not in data
        }
        return data, format_id, extras

    if _looks_like_card_data(root):
        return dict(root), "character-card-v1", {}
    return None


def render_character_card(
    data: dict[str, object],
    extras: dict[str, object],
    source: str,
    fallback_name: str,
    format_id: str,
) -> str:
    """把角色卡字段按小标题写成 Markdown；原文不做清洗，保证提炼时不丢信息。"""
    raw_name = data.get("name")
    display_name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else fallback_name
    label = CARD_FORMAT_LABELS.get(format_id, "Character Card")
    lines = [f"# 角色卡：{display_name}", "", f"> 来源：{source}（{label}）", ""]

    seen: set[str] = set()
    for key, title in CARD_SECTIONS:
        if key not in data:
            continue
        seen.add(key)
        value = data[key]
        if key == "alternate_greetings":
            greetings = value if isinstance(value, list) else [value]
            lines.extend([f"## {title}", ""])
            if not greetings:
                lines.append("（空）")
            for index, greeting in enumerate(greetings, 1):
                lines.extend([f"### 备选开场白 {index}", "", _markdown_value(greeting), ""])
            continue
        lines.extend([f"## {title}", "", _markdown_value(value), ""])

    remaining = [(key, value) for key, value in data.items() if key not in seen]
    remaining.extend(extras.items())
    if remaining:
        lines.extend(["## 其他字段", ""])
        for key, value in remaining:
            lines.extend([f"### {key}", "", _markdown_value(value), ""])
    return "\n".join(lines).rstrip() + "\n"


def _looks_like_world_entry(obj: object) -> bool:
    """世界书条目至少要有 content，或「关键词 + comment」；只凭一个 key 字段不算。"""
    if not isinstance(obj, dict):
        return False
    if isinstance(obj.get("content"), str):
        return True
    has_keys = isinstance(obj.get("key"), (list, str)) or isinstance(obj.get("keys"), (list, str))
    return has_keys and isinstance(obj.get("comment"), str)


def _normalize_world_entries(value: object) -> list[dict[str, object]] | None:
    """把 entries（对象/数组）或 world_info 内容统一成条目列表；不像世界书就返回 None。"""
    if isinstance(value, dict):
        items = list(value.values())
    elif isinstance(value, list):
        items = list(value)
    else:
        return None
    entries = [item for item in items if _looks_like_world_entry(item)]
    if not entries:
        return None
    # entries 里可能混少量元数据；非条目比条目还多时更像别的 JSON，放弃识别以免误判
    if len(items) - len(entries) > len(entries):
        return None
    return entries


def detect_world_info(root: object) -> tuple[list[dict[str, object]], str] | None:
    """识别 World Info / Lorebook：顶层 entries，或 world_info 包裹（可能再套一层 entries）。"""
    if not isinstance(root, dict):
        return None
    if "entries" in root:
        entries = _normalize_world_entries(root["entries"])
        if entries is not None:
            return entries, "entries"
    world_info = root.get("world_info")
    if isinstance(world_info, dict) and "entries" in world_info:
        entries = _normalize_world_entries(world_info["entries"])
        if entries is not None:
            return entries, "world_info.entries"
    if world_info is not None:
        entries = _normalize_world_entries(world_info)
        if entries is not None:
            return entries, "world_info"
    return None


def _entry_disabled(entry: dict[str, object]) -> bool:
    """SillyTavern 用 disable:true；部分导出用 enabled:false。字符串 true 也兼容。"""
    disable = entry.get("disable")
    if disable is True:
        return True
    if isinstance(disable, str) and disable.strip().lower() in ("true", "1", "yes", "on"):
        return True
    return entry.get("enabled") is False


def render_world_info(
    entries: list[dict[str, object]],
    source: str,
    fallback_name: str,
    wrapper: str,
) -> tuple[str, int, int]:
    """每条一个二级标题（comment 或关键词），正文 content；disable:true 跳过。"""
    lines = [f"# 世界书：{fallback_name}", "", f"> 来源：{source}（World Info，{wrapper}）", ""]
    rendered = 0
    skipped = 0
    for index, entry in enumerate(entries, 1):
        if _entry_disabled(entry):
            skipped += 1
            continue
        keys = _as_string_list(entry.get("key", entry.get("keys")))
        secondary = _as_string_list(entry.get("keysecondary", entry.get("secondary_keys")))
        comment = entry.get("comment")
        title = comment.strip() if isinstance(comment, str) and comment.strip() else "、".join(keys)
        title = re.sub(r"\s+", " ", title).strip()[:120]
        if not title:
            title = f"条目 {index}"
        lines.extend([f"## {title}", ""])
        if keys:
            lines.append(f"- 关键词：{'、'.join(keys)}")
        if secondary:
            lines.append(f"- 次级关键词：{'、'.join(secondary)}")
        if keys or secondary:
            lines.append("")
        content = entry.get("content")
        if isinstance(content, str):
            if content.strip():
                lines.extend([content, ""])
            else:
                lines.extend(["（无正文）", ""])
        elif content is not None:
            # 少数导出把 content 写成数组/对象；保留结构而不是当空内容丢掉
            lines.extend([_markdown_value(content), ""])
        else:
            lines.extend(["（无正文）", ""])
        rendered += 1
    if rendered == 0:
        lines.extend(["（没有可用的世界书条目：全部被 disable 跳过）", ""])
    return "\n".join(lines).rstrip() + "\n", rendered, skipped


def _zlib_decompress(data: bytes, where: str, keyword: str) -> bytes:
    """带输出上限的 zlib 解压，避免畸形 PNG 用压缩炸弹把内存撑爆。"""
    try:
        decompressor = zlib.decompressobj()
        out = decompressor.decompress(data, MAX_PNG_TEXT_BYTES + 1)
        out += decompressor.flush()
    except zlib.error as exc:
        raise ValueError(f"{where}: PNG 的 {keyword} 文本块解压失败（{exc}）；文件可能损坏") from exc
    if len(out) > MAX_PNG_TEXT_BYTES or decompressor.unconsumed_tail:
        raise ValueError(
            f"{where}: PNG 的 {keyword} 文本块解压后超过 {human_size(MAX_PNG_TEXT_BYTES)}，拒绝处理；"
            "请确认文件是否被异常构造"
        )
    return out


def _png_text_chunks(data: bytes, where: str) -> dict[str, str]:
    """扫描 PNG 的 tEXt/zTXt/iTXt 块，只留 chara/ccv3，其余文本块直接忽略。

    只依赖标准库 struct/zlib：不装 Pillow 也能读内嵌角色卡。
    """
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(
            f"{where}: 不是有效的 PNG（文件头不是 PNG 签名）；"
            "如果这只是普通图片，请改用 agent 的图片理解工具转成文字"
        )
    chunks: dict[str, str] = {}
    pos = len(PNG_SIGNATURE)
    saw_iend = False
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        payload_start = pos + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(data):
            raise ValueError(
                f"{where}: PNG 数据块 {chunk_type!r} 被截断（声明长度 {length}，剩余 {len(data) - payload_start} 字节）；"
                "文件可能损坏，请重新导出"
            )
        payload = data[payload_start:payload_end]
        pos = payload_end + 4  # 跳过 CRC（角色卡文本块不需要校验 CRC）
        if chunk_type == b"IEND":
            saw_iend = True
            break
        if chunk_type not in (b"tEXt", b"zTXt", b"iTXt"):
            continue

        keyword_bytes, sep, rest = payload.partition(b"\x00")
        if not sep:
            continue
        keyword = keyword_bytes.decode("latin-1").strip().lower()
        if keyword not in PNG_CARD_KEYWORDS:
            continue

        if chunk_type == b"tEXt":
            # tEXt 规范是 latin-1；chara 的值本身是 base64 ASCII
            text = rest.decode("latin-1")
        elif chunk_type == b"zTXt":
            if not rest:
                raise ValueError(f"{where}: PNG 的 {keyword} zTXt 块缺少压缩数据；文件可能损坏")
            method, compressed = rest[0], rest[1:]
            if method != 0:
                raise ValueError(f"{where}: PNG 的 {keyword} zTXt 块使用了不支持的压缩方式 {method}")
            text = _zlib_decompress(compressed, where, keyword).decode("latin-1")
        else:  # iTXt
            if len(rest) < 2:
                raise ValueError(f"{where}: PNG 的 {keyword} iTXt 块结构不完整；文件可能损坏")
            compression_flag, method = rest[0], rest[1]
            fields = rest[2:].split(b"\x00", 2)
            if len(fields) != 3:
                raise ValueError(f"{where}: PNG 的 {keyword} iTXt 块结构不完整；文件可能损坏")
            _language, _translated, text_bytes = fields
            if compression_flag:
                if method != 0:
                    raise ValueError(f"{where}: PNG 的 {keyword} iTXt 块使用了不支持的压缩方式 {method}")
                text_bytes = _zlib_decompress(text_bytes, where, keyword)
            try:
                text = text_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{where}: PNG 的 {keyword} iTXt 块不是合法 UTF-8（{exc}）；文件可能损坏") from exc
        chunks.setdefault(keyword, text)
    if not saw_iend:
        raise ValueError(f"{where}: PNG 缺少 IEND 结束块；文件可能被截断")
    return chunks


def _decode_png_card_base64(value: str, where: str, keyword: str) -> bytes:
    """chara/ccv3 的值是 base64 编码的 JSON；容忍换行与缺失的 padding。"""
    compact = re.sub(r"\s+", "", value)
    if not compact:
        raise ValueError(f"{where}: PNG 的 {keyword} 块为空，没有可解码的角色卡数据")
    padded = compact + "=" * (-len(compact) % 4)
    try:
        return base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        pass
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"{where}: PNG 的 {keyword} 块不是合法 base64（{exc}）；角色卡可能损坏，请重新从原应用导出"
        ) from exc


def _decode_png_card_json(raw: bytes, where: str, keyword: str) -> object:
    try:
        text, _encoding = decode_text(raw, f"{where} 内嵌 {keyword} 数据")
    except ValueError as exc:
        raise ValueError(f"{where}: PNG 的 {keyword} 块解码后不是 UTF-8/GB18030 文本（{exc}）") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{where}: PNG 的 {keyword} 块解码后不是合法 JSON（第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}）；"
            "角色卡可能损坏，请重新从原应用导出"
        ) from exc
    except RecursionError as exc:
        raise ValueError(f"{where}: PNG 的 {keyword} 数据嵌套层级过深，无法解析；请重新从原应用导出") from exc


def extract_png_source(data: bytes, where: str, fallback_name: str) -> tuple[str, str] | None:
    """读取 PNG 内嵌角色卡；返回 (Markdown, 格式 id)；普通图片（无 chara/ccv3）返回 None。"""
    chunks = _png_text_chunks(data, where)
    for keyword in PNG_CARD_KEYWORDS:
        if keyword not in chunks:
            continue
        raw = _decode_png_card_base64(chunks[keyword], where, keyword)
        root = _decode_png_card_json(raw, where, keyword)
        card = detect_character_card(root)
        if card is None and isinstance(root, dict) and isinstance(root.get("data"), dict):
            # PNG 里已经确认是角色卡数据，字段稀疏时按 V2 结构兜底，不因启发式过严而失败
            data_obj = root["data"]
            extras = {key: value for key, value in root.items() if key not in CARD_META_KEYS and key not in data_obj}
            version = root.get("spec_version")
            version_text = str(version).strip() if isinstance(version, (str, int, float)) else ""
            format_id = "character-card-v3" if version_text.startswith("3") else "character-card-v2"
            card = (data_obj, format_id, extras)
        if card is None:
            raise ValueError(
                f"{where}: PNG 的 {keyword} 数据是 JSON，但没有角色卡字段（缺少 name/description 等）；"
                "请确认这是 Character Card V2/V3 角色卡"
            )
        data_obj, format_id, extras = card
        return render_character_card(data_obj, extras, where, fallback_name, format_id), format_id
    return None


def extract_json_source(text: str, where: str, fallback_name: str) -> tuple[str, str, str, dict[str, object], list[str]]:
    """识别并转换 .json；返回 (Markdown 或原文, kind, format, 统计附加字段, 警告列表)。"""
    try:
        root = json.loads(text)
    except json.JSONDecodeError as exc:
        # 非法 JSON 不当角色卡猜，也不静默当普通文本：保留原文 + 给可操作警告
        return text, "json-raw", "invalid-json", {}, [
            f"JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}）；已按原文保留到 sources，请检查导出是否完整"
        ]
    except RecursionError:
        return text, "json-raw", "invalid-json", {}, [
            "JSON 嵌套层级过深，无法解析；已按原文保留到 sources，请检查导出是否异常"
        ]

    # 先判世界书：顶层 entries 是强结构信号；避免极少数带 name/description 的 lorebook 被误当 V1 角色卡
    world = detect_world_info(root)
    if world is not None:
        entries, wrapper = world
        # 世界书顶层常有 name/title；用它当标题比文件名更可读
        book_name = fallback_name
        if isinstance(root, dict):
            for key in ("name", "title"):
                value = root.get(key)
                if isinstance(value, str) and value.strip():
                    book_name = re.sub(r"\s+", " ", value).strip()[:120]
                    break
        markdown, rendered, skipped = render_world_info(entries, where, book_name, wrapper)
        warnings = [f"世界书有 {skipped} 条 disable:true 已跳过"] if skipped else []
        extra: dict[str, object] = {"entries": rendered}
        if skipped:
            extra["disabled"] = skipped
        return markdown, "world-info", "world-info", extra, warnings

    card = detect_character_card(root)
    if card is not None:
        data_obj, format_id, extras = card
        return render_character_card(data_obj, extras, where, fallback_name, format_id), "character-card", format_id, {}, []

    # 合法 JSON 但不是两种目标结构：保留原文供人工判断，绝不当角色卡处理
    return text, "json-raw", "json", {}, [
        "识别为 JSON，但不是角色卡（Character Card V1/V2/V3）或世界书（entries/world_info）结构；"
        "已按原文保留到 sources，请人工确认格式"
    ]


# ── 聊天记录解析 ─────────────────────────────────────────────────────────────

TS_HEADER = re.compile(
    r"^\s*\[?(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*(.*)$"
)
NAME_TS = re.compile(
    r"^\s*([^\s:：\[\]]{1,40})\s+(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$"
)
DATE_ONLY = re.compile(r"^\s*\[?(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\]?\s*$")
SPEAKER_CONTENT = re.compile(r"^\s*([^:：]{1,40})[:：]\s*(.*)$")
QQ_SUFFIX = re.compile(r"\s*[\(（<]\s*\d{3,}\s*[\)）>]\s*$")


def _clean_speaker(raw: str) -> str:
    speaker = QQ_SUFFIX.sub("", raw.strip())
    speaker = speaker.strip(" \t[]【】<>《》\"'“”‘’")
    return speaker[:40] or "未知"


def parse_chat(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    current_date: str | None = None
    date_mode = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            body = current["text"].strip()
            if body:
                messages.append({"ts": current["ts"], "speaker": current["speaker"], "text": body})
            current = None

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            if current is not None:
                current["text"] += "\n"
            continue

        match = NAME_TS.match(line)
        if match:
            flush()
            date_mode = False
            current = {
                "ts": _iso_datetime(match.group(2), match.group(3), match.group(4), match.group(5), match.group(6), match.group(7)),
                "speaker": _clean_speaker(match.group(1)),
                "text": "",
            }
            continue

        match = DATE_ONLY.match(line)
        if match:
            flush()
            current_date = _iso_date(match.group(1), match.group(2), match.group(3))
            date_mode = True
            continue

        match = TS_HEADER.match(line)
        if match:
            flush()
            date_mode = False
            rest = match.group(7).strip()
            speaker = ""
            body = ""
            if rest:
                speaker_match = SPEAKER_CONTENT.match(rest)
                if speaker_match:
                    speaker = _clean_speaker(speaker_match.group(1))
                    body = speaker_match.group(2)
                else:
                    speaker = _clean_speaker(rest)
            current = {
                "ts": _iso_datetime(match.group(1), match.group(2), match.group(3), match.group(4), match.group(5), match.group(6)),
                "speaker": speaker,
                "text": body,
            }
            continue

        # 只有日期分组的导出格式：每条「昵称: 内容」都是一条独立消息
        if date_mode:
            speaker_match = SPEAKER_CONTENT.match(line)
            if speaker_match:
                flush()
                current = {
                    "ts": current_date or "",
                    "speaker": _clean_speaker(speaker_match.group(1)),
                    "text": speaker_match.group(2),
                }
            elif current is not None:
                current["text"] += line + "\n"
            continue

        if current is None:
            continue

        if not current["speaker"]:
            speaker_match = SPEAKER_CONTENT.match(line)
            if speaker_match:
                current["speaker"] = _clean_speaker(speaker_match.group(1))
                current["text"] += speaker_match.group(2)
                continue
        current["text"] += line + "\n"

    flush()
    return messages


def looks_like_chat(messages: list[dict[str, str]], text: str) -> bool:
    if len(messages) < 3:
        return False
    non_empty_lines = sum(1 for line in text.split("\n") if line.strip())
    if non_empty_lines and len(messages) < non_empty_lines * 0.03:
        return False
    named = sum(1 for message in messages if message["speaker"] != "未知")
    return named >= 2


# ── 主流程 ──────────────────────────────────────────────────────────────────


def iter_input_files(root: Path, output_dir: Path, recursive: bool) -> list[Path]:
    output_resolved = output_dir.resolve()
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in JUNK_DIRS and not os.path.islink(os.path.join(dirpath, name))
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            try:
                path.resolve().relative_to(output_resolved)
                continue
            except ValueError:
                pass
            if name in JUNK_NAMES or name.startswith("."):
                continue
            files.append(path)
        if not recursive:
            break
    return files


def process_file(path: Path, input_root: Path) -> dict[str, object]:
    """返回一个统计条目；提取失败时条目带 error 字段。"""
    entry: dict[str, object] = {
        "source": str(path.relative_to(input_root)).replace(os.sep, "/"),
        "type": SUPPORTED_EXTS.get(path.suffix.lower(), "unknown"),
        "chars": 0,
        "chat": False,
        "messages": 0,
    }
    try:
        size = path.stat().st_size
    except OSError as exc:
        entry["error"] = f"无法读取文件信息：{exc}"
        return entry
    if size > MAX_INPUT_BYTES:
        entry["error"] = f"文件 {human_size(size)} 超过 {human_size(MAX_INPUT_BYTES)}，请先拆分"
        return entry
    data = path.read_bytes()
    file_type = SUPPORTED_EXTS.get(path.suffix.lower())

    try:
        if file_type in ("txt", "md"):
            text, encoding = decode_text(data, entry["source"])
            entry["encoding"] = encoding
            if file_type == "md":
                text = re.sub(r"^\ufeff", "", text)
        elif file_type == "html":
            raw, encoding = decode_text(data, entry["source"])
            entry["encoding"] = encoding
            text = extract_html(raw)
        elif file_type == "docx":
            entry["encoding"] = "-"
            text = extract_docx(data, entry["source"])
        elif file_type == "pdf":
            entry["encoding"] = "-"
            text = extract_pdf(data, entry["source"])
        elif file_type == "json":
            raw_text, encoding = decode_text(data, entry["source"])
            entry["encoding"] = encoding
            text, kind, format_id, extra, json_warnings = extract_json_source(
                raw_text, entry["source"], Path(entry["source"]).stem
            )
            entry["kind"] = kind
            entry["format"] = format_id
            entry.update(extra)
            entry["_warnings"] = json_warnings
        elif file_type == "png":
            entry["encoding"] = "-"
            png_card = extract_png_source(data, entry["source"], Path(entry["source"]).stem)
            if png_card is None:
                # 普通 PNG 不是「失败」：沿用原有「图片不转文字」体验，只警告跳过
                entry["_skip"] = "PNG 未包含角色卡数据（chara/ccv3 文本块），按普通图片跳过；如需图片里的文字请用 agent 的图片理解工具"
                return entry
            text, format_id = png_card
            entry["kind"] = "character-card"
            entry["format"] = format_id
            entry["container"] = "png"
        else:
            entry["error"] = "不支持的格式"
            return entry
    except PdfUnavailable:
        entry["error"] = "PDF_NO_LIB"
        return entry
    except ValueError as exc:
        entry["error"] = str(exc)
        return entry

    if not text.strip():
        if file_type == "pdf":
            entry["error"] = "未提取到文字（可能是扫描件/图片型 PDF，需要 OCR 或 agent 的 PDF 阅读工具）"
        elif file_type == "docx":
            entry["error"] = "文档里没有可提取的文字（可能全是图片/文本框，需要用 agent 的文档阅读工具）"
        elif file_type == "json":
            entry["error"] = "JSON 内容为空（文件可能是空白或编码异常），没有可保留的原文"
        else:
            entry["error"] = "提取结果为空（文件可能是空白或编码异常）"
        return entry

    entry["chars"] = len(text)
    entry["text"] = text
    return entry


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="把 txt/md/html/docx/pdf/角色卡 JSON/PNG 提取成 sources/*.md + messages.jsonl + stats.json。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="输入目录（可递归）")
    parser.add_argument("-o", "--out", default="提取结果", help="输出目录，默认 ./提取结果")
    parser.add_argument("--no-recursive", action="store_true", help="只处理输入目录第一层文件")
    args = parser.parse_args(argv)

    input_dir = Path(args.input).resolve()
    if not input_dir.is_dir():
        print(f"[错误] 输入目录不存在：{input_dir}", file=sys.stderr)
        return 1
    output_dir = Path(args.out).resolve()
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    input_files = iter_input_files(input_dir, output_dir, recursive=not args.no_recursive)
    stats_entries: list[dict[str, object]] = []
    warnings: list[dict[str, str]] = []
    chat_messages: list[dict[str, str]] = []
    used_names: set[str] = set()
    failed = 0
    skipped_unknown = 0

    for path in input_files:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            if suffix == ".doc":
                warnings.append({"source": str(path.relative_to(input_dir)), "message": "旧版 .doc 不支持，请另存为 .docx 或 .txt"})
            elif suffix in (".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                warnings.append({"source": str(path.relative_to(input_dir)), "message": "图片不提取文字；如需内容请用 agent 的图片理解工具先转成文字（PNG 角色卡请用 .png 输入）"})
            else:
                skipped_unknown += 1
            continue
        entry = process_file(path, input_dir)
        # 识别过程中的提示（例如 disable 条目被跳过、未知 JSON 已保留原文）统一进全局 warnings
        for message in entry.pop("_warnings", []):
            warnings.append({"source": str(entry["source"]), "message": str(message)})
        skip_message = entry.pop("_skip", None)
        if skip_message:
            warnings.append({"source": str(entry["source"]), "message": str(skip_message)})
            continue
        stats_entries.append(entry)
        if entry.get("error"):
            failed += 1
            continue
        text = str(entry.pop("text"))
        messages = parse_chat(text) if SUPPORTED_EXTS.get(suffix) in ("txt", "md") else []
        if messages and looks_like_chat(messages, text):
            entry["chat"] = True
            entry["messages"] = len(messages)
            chat_messages.extend(messages)
        out_name = sanitize_file_name(Path(entry["source"]).stem)
        out_name = next_unique_name(used_names, out_name)
        used_names.add(out_name)
        entry["output"] = f"sources/{out_name}"
        write_text(sources_dir / out_name, text if text.endswith("\n") else text + "\n")

    # messages.jsonl：一行一条，ts / speaker / text（契约字段，不额外加字段）
    jsonl_path = output_dir / "messages.jsonl"
    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as handle:
        for message in chat_messages:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    chat_files = sum(1 for entry in stats_entries if entry.get("chat"))
    sources_written = sum(1 for entry in stats_entries if entry.get("output"))
    total_chars = sum(int(entry.get("chars", 0)) for entry in stats_entries)
    character_cards = sum(1 for entry in stats_entries if entry.get("kind") == "character-card")
    png_cards = sum(
        1
        for entry in stats_entries
        if entry.get("kind") == "character-card" and entry.get("container") == "png"
    )
    world_books = sum(1 for entry in stats_entries if entry.get("kind") == "world-info")
    world_entries = sum(int(entry.get("entries", 0)) for entry in stats_entries if entry.get("kind") == "world-info")
    world_disabled = sum(int(entry.get("disabled", 0)) for entry in stats_entries if entry.get("kind") == "world-info")
    raw_json = sum(1 for entry in stats_entries if entry.get("kind") == "json-raw")
    stats = {
        "tool": "umi-feiyu-pack/extract_sources.py",
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputDir": str(input_dir),
        "outputDir": str(output_dir),
        "files": stats_entries,
        "totals": {
            "files": len(stats_entries),
            "failed": failed,
            "skippedUnknown": skipped_unknown,
            "chars": total_chars,
            "chatFiles": chat_files,
            "messages": len(chat_messages),
            # kind 在 files[] 里逐条标记；totals 汇总方便 agent 快速判断输入构成
            "characterCards": character_cards,
            "worldInfo": world_books,
            "worldInfoEntries": world_entries,
            "jsonRaw": raw_json,
        },
        "warnings": warnings,
    }
    write_json(output_dir / "stats.json", stats)

    print(f"[完成] 提取完成：{output_dir}")
    print(f"  输入文件 : {len(input_files)} 个（已提取 {len(stats_entries)} / 失败 {failed} / 跳过未知 {skipped_unknown}）")
    print(f"  sources/ : {sources_written} 个 .md")
    print(f"  聊天文件 : {chat_files} 个，消息 {len(chat_messages)} 条")
    if character_cards or world_books or raw_json:
        print(f"  角色卡   : {character_cards} 个（其中 PNG 内嵌 {png_cards} 个）")
        print(f"  世界书   : {world_books} 个，可用条目 {world_entries} 条（跳过 disable {world_disabled} 条）")
        if raw_json:
            print(f"  JSON 原文: {raw_json} 个未识别，已原样保留到 sources（见上方警告）")
    print(f"  字符数   : {total_chars}")
    print(f"  messages.jsonl / stats.json 已写入")
    if warnings:
        print(f"  警告 {len(warnings)} 条：")
        for warning in warnings[:30]:
            print(f"    - {warning['source']}: {warning['message']}")
    failed_entries = [entry for entry in stats_entries if entry.get("error")]
    if failed_entries:
        print()
        print(f"[需要处理] {len(failed_entries)} 个文件没提取成功：")
        for entry in failed_entries:
            error = str(entry["error"])
            if error == "PDF_NO_LIB":
                print(f"  - {entry['source']}: 没有可用的 PDF 解析库（pypdf / pdfminer.six 都没装）")
                print("    处理方式（任选其一）：")
                print("      1) 安装可选依赖后重跑：python -m pip install pypdf")
                print("      2) 用 agent 的文档/PDF 阅读工具把该 PDF 转成文本，另存为 <输入目录>/<同名>.md 后重跑")
                print("      3) 用 office/PDF 技能把它转成 .docx 再放进输入目录重跑")
            else:
                print(f"  - {entry['source']}: {error}")
    print()
    print("[下一步] 阅读 sources/*.md 与 messages.jsonl，按 references/conversion-guide.md 生成 pack-plan.json，")
    print("         再运行：python build_pack.py pack-plan.json -o <资料包目录>")
    if failed:
        print("[提示] 有文件提取失败；如果这些文件含关键设定，请先按上面的替代方案补齐后再生成资料包。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
