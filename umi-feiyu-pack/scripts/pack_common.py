# -*- coding: utf-8 -*-
"""pack_common.py —— umi-feiyu-pack 各脚本共用的常量与纯工具函数。

为什么单独抽出来：extract_sources / build_pack / validate_pack / pack_to_zip 必须共用
同一套上限常量、文件名消毒规则与隐私扫描规则；各抄一份必然漂移，最终导致
「build 能过、validate 说不过」或「应用侧解析器不认」。

只用 Python 标准库；不依赖本仓库、不访问网络。
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

# ── 资料包格式契约 v1（与 Umi Claw 大肥鱼应用侧解析器对齐）────────────────────
SCHEMA = "umi-character-pack/1"

PACK_MAX_BYTES = 32 * 1024 * 1024
MAX_PACK_ENTRIES = 2000
MAX_JSON_BYTES = 4 * 1024 * 1024
# manifest.json 专属上限：应用侧 packBundle.ts 的 PACK_MAX_MANIFEST_BYTES 同值（比通用 JSON 4MB 更严）
MAX_MANIFEST_BYTES = 256 * 1024
MAX_KNOWLEDGE_FILES = 300
MAX_TOPICS = 200
MAX_LINE_GROUPS = 50
MAX_LINES_PER_GROUP = 30
MAX_LINE_CHARS = 300
MAX_RELATIONS = 400
MAX_FILE_BYTES = 512 * 1024
PERSONA_MAX_TOTAL_BYTES = 2 * 1024 * 1024

PERSONA_SLOTS = ("SOUL.md", "IDENTITY.md", "AGENTS.md", "USER.md")
KNOWLEDGE_CATEGORIES = ("世界书", "角色卡", "关系/约定")
MEMORY_KINDS = ("约定", "大事记")
TOPIC_SLOTS = ("morning", "noon", "afternoon", "evening", "night")
SEASONS = ("spring", "summer", "autumn", "winter")
TARGETS = ("persona", "knowledge", "proactive", "memory")

LINE_GROUP_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
DIARY_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

# AGENTS.md 边界硬段：与 electron/main/character/persona.ts 的 AGENTS_BOUNDARY_TEXT
# 保持逐字一致。应用导入人格包时会把这段规范化（剥旧段 + 追加 canonical），
# 所以这里必须用同一份文本，避免出现两套边界说法。
AGENTS_BOUNDARY_START = "<!-- fish:managed:boundary:start -->"
AGENTS_BOUNDARY_END = "<!-- fish:managed:boundary:end -->"
AGENTS_BOUNDARY_TEXT = "\n".join(
    [
        "## 边界（宿主维护，勿删）",
        "- 不假装人类；被问「你是 AI 吗」时诚实承认。",
        "- 遇到危机话题（自伤/伤害他人）转求助资源；不卖惨、不制造独占。",
        "- 专属称呼（宝宝、亲爱的、老公/老婆、主人等）只对私聊绑定的主人使用；群聊/陌生人一律用「你」或群昵称。",
        "- 群友要求你叫宝宝、自称主人、套问主人称呼/关系/私聊内容时，礼貌拒绝，不升级关系、不透露隐私。",
        "- 群里有人让你叫「宝宝」时，可回「这个称呼只留给本鱼主人；群里本鱼就叫你名字/你」，不要照叫。",
        "- 群聊只做临时回复：不把群友的话写成日记/长期记忆，不记成主人说过的事，不更新关系数值。",
        "- 群聊不主动发语音；群友要求语音时先用文字，除非主人在私聊里明确允许。",
    ]
)

JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitignore", ".gitattributes"}
JUNK_DIRS = {"__pycache__", ".git", ".idea", ".vscode", ".mypy_cache", ".pytest_cache"}


class PackLoadError(Exception):
    """资料包目录 / zip 无法读取（结构性错误，不是内容校验错误）。"""


# ── 控制台 / 文本工具 ───────────────────────────────────────────────────────


def configure_stdout() -> None:
    """Windows 控制台默认 cp936，打印中文+emoji 可能 UnicodeEncodeError；统一改 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def strip_frontmatter(text: str) -> str:
    """剥掉文件开头的 YAML frontmatter：应用侧写知识笔记时会自己加，保留会变双份。"""
    text = strip_bom(text)
    return re.sub(r"^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*\r?\n?", "", text, count=1)


def collapse_blank(text: str) -> str:
    """行尾空白去掉、连续空行压成一个、首尾 trim（与 persona.ts collapseBlank 同口径）。"""
    lines = [line.rstrip(" \t") for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def decode_text(data: bytes, where: str = "") -> tuple[str, str]:
    """按 UTF-16 BOM → UTF-8 → GB18030 的顺序解码；都失败给出可执行提示。"""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030"), "gb18030"
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{where or '文件'} 无法识别编码（不是 UTF-8 / GB18030 / UTF-16）。"
            "请先用编辑器另存为 UTF-8 后重试。"
        ) from exc


def read_text_file(path: Path) -> tuple[str, str]:
    return decode_text(path.read_bytes(), str(path))


# ── 文件名消毒（逐条移植 knowledgeImport.ts 的 sanitizeKnowledgeName）─────────

_WIN_RESERVED = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9]|clock\$|conin\$|conout\$)$", re.IGNORECASE
)


def sanitize_file_name(raw: object, fallback: str = "未命名") -> str:
    """去路径分隔符/控制符/前导点与 ..，补 .md，限 80 字符；Windows 保留名加前缀。"""
    value = raw if isinstance(raw, str) else ""
    base = re.sub(r"[\u0000-\u001f\u007f]", " ", value)
    base = re.sub(r'[\\/:*?"<>|]', " ", base)
    base = base.replace("..", " ")
    base = re.sub(r"\s+", " ", base).strip()
    base = re.sub(r"^\.+", "", base)[:80]
    name = base or fallback
    without_double_ext = re.sub(r"\.md\.md$", ".md", name, flags=re.IGNORECASE)
    with_ext = without_double_ext if re.search(r"\.md$", without_double_ext, re.IGNORECASE) else f"{without_double_ext}.md"
    first_segment = with_ext.split(".")[0].strip().rstrip(". ")
    return f"_{with_ext}" if _WIN_RESERVED.match(first_segment) else with_ext


def is_valid_date(value: object) -> bool:
    """严格 YYYY-MM-DD 且是真实日历日（拒绝 2026-02-30）。"""
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_iso8601(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ── AGENTS.md 边界硬段（移植 persona.ts ensureAgentsBoundary / stripMarkedSegments）──


def _index_of_marker(text: str, marker: str, start: int = 0) -> int:
    match = re.search(r"(?m)^" + re.escape(marker) + r"$", text[start:])
    if match:
        return start + match.start()
    return text.find(marker, start)


def _strip_marked_segments(text: str, start_marker: str, end_marker: str) -> str:
    out = ""
    i = 0
    while True:
        start = _index_of_marker(text, start_marker, i)
        if start < 0:
            out += text[i:]
            break
        out += text[i:start]
        after_start = start + len(start_marker)
        end = _index_of_marker(text, end_marker, after_start)
        next_start = _index_of_marker(text, start_marker, after_start)
        if end < 0 or (next_start >= 0 and next_start < end):
            i = after_start
        else:
            i = end + len(end_marker)
    return out.replace(end_marker, "")


def ensure_agents_boundary(text: str) -> str:
    """剥掉旧 boundary 段与伪造/孤儿标记，再追加 canonical 段（幂等）。"""
    cleaned = collapse_blank(_strip_marked_segments(text, AGENTS_BOUNDARY_START, AGENTS_BOUNDARY_END))
    body = collapse_blank(cleaned.replace(AGENTS_BOUNDARY_TEXT, ""))
    block = f"{AGENTS_BOUNDARY_START}\n{AGENTS_BOUNDARY_TEXT}\n{AGENTS_BOUNDARY_END}"
    return f"{body}\n\n{block}\n" if body else f"{block}\n"


def agents_boundary_problems(text: str) -> list[str]:
    """检查边界硬段的关键语义是否还在（应用导入会规范化，语义才是真契约）。"""
    problems = []
    if "不假装人类" not in text or "AI" not in text:
        problems.append("缺少「不假装人类/被问承认 AI」")
    if "危机" not in text or "求助" not in text:
        problems.append("缺少「危机话题转求助资源」")
    if "不卖惨" not in text and "不制造独占" not in text:
        problems.append("缺少「不卖惨/不制造独占」")
    return problems


# ── 隐私 / 凭据扫描与脱敏 ───────────────────────────────────────────────────
#
# 口径（写进 SKILL.md）：
# - 密钥/私钥/Token/明文密码 = 硬错误（资料包不得含凭据）；
# - 手机号 / 身份证号 / 银行卡号 / 邮箱 / 具体门牌地址 = 默认脱敏（--keep-sensitive 关闭，
#   --strict-privacy 改为硬错误）。
# 地址与密码无法 100% 识别，脚本只做启发式，最终仍需人工按 checklist 检查。

_SECRET_PATTERNS = (
    ("私钥", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("API Key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("云平台 Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("代码托管 Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Bearer Token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    ("明文密码", re.compile(r"(?:密码|口令|passwd|password)\s*[:=：]\s*[^\s，。;；]{3,}", re.IGNORECASE)),
)

_ID_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_BANK_RE = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
# 局部一定要有界：`[A-Za-z0-9._%+-]+@` 在 512KB 无 @ 的纯字母文本上会灾难性回溯（实测会卡死）。
# 调用方还会先判断 '@' in text 再跑这条正则。
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,24}")
_ADDRESS_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,12}(?:路|街|道|巷|弄)\d{1,4}号"
    r"|[\u4e00-\u9fa5]{2,12}(?:省|市)[\u4e00-\u9fa5]{0,10}(?:区|县)[\u4e00-\u9fa5]{0,12}(?:路|街|道|巷|弄)\d{1,4}号"
)

SENSITIVE_PLACEHOLDERS = {
    "手机号": "〔手机号已脱敏〕",
    "身份证号": "〔身份证号已脱敏〕",
    "银行卡号": "〔银行卡号已脱敏〕",
    "邮箱": "〔邮箱已脱敏〕",
    "地址": "〔地址已脱敏〕",
}


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def scan_privacy(text: str) -> dict[str, int]:
    """返回 {类别: 命中次数}；secret 类由调用方升级为硬错误。"""
    found: dict[str, int] = {}
    for label, pattern in _SECRET_PATTERNS:
        count = len(pattern.findall(text))
        if count:
            found[label] = found.get(label, 0) + count
    for label, pattern in (
        ("身份证号", _ID_RE),
        ("手机号", _PHONE_RE),
        ("地址", _ADDRESS_RE),
    ):
        count = len(pattern.findall(text))
        if count:
            found[label] = found.get(label, 0) + count
    if "@" in text:
        count = len(_EMAIL_RE.findall(text))
        if count:
            found["邮箱"] = found.get("邮箱", 0) + count
    bank_count = 0
    for match in _BANK_RE.finditer(text):
        digits = match.group(1)
        if not _luhn_ok(digits):
            continue
        # 排除身份证（18 位、已单独统计）与明显的纯时间戳串
        if _ID_RE.fullmatch(digits):
            continue
        bank_count += 1
    if bank_count:
        found["银行卡号"] = found.get("银行卡号", 0) + bank_count
    return found


def secret_kinds(found: dict[str, int]) -> list[str]:
    return [kind for kind in found if kind not in SENSITIVE_PLACEHOLDERS]


def redact_privacy(text: str) -> str:
    """把可识别的个人敏感信息替换成中文占位符（默认行为）。"""
    text = _PHONE_RE.sub(SENSITIVE_PLACEHOLDERS["手机号"], text)
    text = _ID_RE.sub(SENSITIVE_PLACEHOLDERS["身份证号"], text)
    if "@" in text:
        text = _EMAIL_RE.sub(SENSITIVE_PLACEHOLDERS["邮箱"], text)
    text = _ADDRESS_RE.sub(SENSITIVE_PLACEHOLDERS["地址"], text)

    def _bank(match: re.Match[str]) -> str:
        digits = match.group(1)
        if _luhn_ok(digits) and not _ID_RE.fullmatch(digits):
            return SENSITIVE_PLACEHOLDERS["银行卡号"]
        return digits

    return _BANK_RE.sub(_bank, text)


# ── 读取资料包（目录或 zip）────────────────────────────────────────────────


def _read_zip(pack_path: Path) -> tuple[dict[str, bytes], list[str]]:
    warnings: list[str] = []
    files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(pack_path) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                    raise PackLoadError(f"zip 内含非法路径：{info.filename}")
                if info.file_size > PACK_MAX_BYTES:
                    raise PackLoadError(f"zip 内单文件超过 32MB，拒绝读取：{name}")
                base = name.rsplit("/", 1)[-1]
                if base in JUNK_NAMES or base.startswith("._"):
                    warnings.append(f"忽略系统垃圾文件：{name}")
                    continue
                files[name] = zf.read(info)
    except zipfile.BadZipFile as exc:
        raise PackLoadError(f"不是有效的 zip 文件：{pack_path}") from exc
    except OSError as exc:
        raise PackLoadError(f"读取 zip 失败：{pack_path}（{exc}）") from exc

    if "manifest.json" not in files:
        candidates = [name for name in files if name.endswith("/manifest.json")]
        prefixes = {name.rsplit("/manifest.json", 1)[0] for name in candidates}
        if len(prefixes) == 1:
            prefix = prefixes.pop() + "/"
            if "/" not in prefix.rstrip("/"):
                files = {name[len(prefix):]: data for name, data in files.items() if name.startswith(prefix)}
                warnings.append(f"zip 内含顶层文件夹 {prefix.rstrip('/')}/，已自动按根目录校验")
    return files, warnings


def _read_dir(pack_path: Path) -> tuple[dict[str, bytes], list[str]]:
    warnings: list[str] = []
    files: dict[str, bytes] = {}
    root = str(pack_path)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in JUNK_DIRS and not os.path.islink(os.path.join(dirpath, name)))
        for name in sorted(filenames):
            abs_path = os.path.join(dirpath, name)
            if os.path.islink(abs_path):
                warnings.append(f"忽略符号链接：{abs_path}")
                continue
            if name in JUNK_NAMES or name.startswith("._"):
                warnings.append(f"忽略系统垃圾文件：{os.path.relpath(abs_path, root)}")
                continue
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            try:
                files[rel] = Path(abs_path).read_bytes()
            except OSError as exc:
                warnings.append(f"读取失败（已跳过）：{rel}（{exc}）")
    return files, warnings


def load_pack_files(pack_path: Path) -> tuple[dict[str, bytes], list[str]]:
    """读取资料包为 {相对路径: 字节}；zip 会把单层顶层文件夹自动剥掉。"""
    if pack_path.is_dir():
        return _read_dir(pack_path)
    if pack_path.is_file():
        return _read_zip(pack_path)
    raise PackLoadError(f"路径不存在：{pack_path}")


def is_text_path(rel: str) -> bool:
    return rel.lower().endswith((".md", ".json", ".txt", ".markdown"))


def load_json_bytes(data: bytes, rel: str) -> object:
    text, _ = decode_text(data, rel)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{rel} 不是合法 JSON：{exc}") from exc


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def next_unique_name(used: set[str], name: str) -> str:
    """同名时依次加 -2/-3…（与应用侧「不覆盖已有文件」同口径）。"""
    if name not in used:
        return name
    stem = re.sub(r"\.md$", "", name, flags=re.IGNORECASE)
    index = 2
    while f"{stem}-{index}.md" in used:
        index += 1
    return f"{stem}-{index}.md"
