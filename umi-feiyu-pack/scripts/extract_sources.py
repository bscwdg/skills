#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_sources.py —— 把 txt/md/html/docx/pdf 提取成 sources/*.md + messages.jsonl + stats.json。

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
    <输出目录>/sources/*.md      每个输入文件一份纯文本提取结果
    <输出目录>/messages.jsonl    所有聊天文件的消息（ts / speaker / text）
    <输出目录>/stats.json        每个文件的提取统计与警告（供 agent 自检）

PDF 需要可选依赖 pypdf（或 pdfminer.six）；没装时不会静默失败，会给出替代方案并以退出码 1 结束。
"""

from __future__ import annotations

import argparse
import html.parser
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
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
}

MAX_INPUT_BYTES = 64 * 1024 * 1024

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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
        else:
            entry["error"] = "提取结果为空（文件可能是空白或编码异常）"
        return entry

    entry["chars"] = len(text)
    entry["text"] = text
    return entry


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="把 txt/md/html/docx/pdf 提取成 sources/*.md + messages.jsonl + stats.json。",
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
            elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                warnings.append({"source": str(path.relative_to(input_dir)), "message": "图片不提取文字；如需内容请用 agent 的图片理解工具先转成文字"})
            else:
                skipped_unknown += 1
            continue
        entry = process_file(path, input_dir)
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
        },
        "warnings": warnings,
    }
    write_json(output_dir / "stats.json", stats)

    print(f"[完成] 提取完成：{output_dir}")
    print(f"  输入文件 : {len(input_files)} 个（已提取 {len(stats_entries)} / 失败 {failed} / 跳过未知 {skipped_unknown}）")
    print(f"  sources/ : {sources_written} 个 .md")
    print(f"  聊天文件 : {chat_files} 个，消息 {len(chat_messages)} 条")
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
