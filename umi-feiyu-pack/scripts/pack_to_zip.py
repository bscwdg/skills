#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_to_zip.py —— 把资料包目录打成 zip（zip 根目录直接是 manifest.json 等文件）。

注意：这是「资料包 zip」（给 Umi Claw「大肥鱼 → 资料包 → 导入 zip」用），
不是「技能 zip」。技能 zip 需要顶层目录 umi-feiyu-pack/，见 SKILL.md。

用法：
    python pack_to_zip.py <资料包目录> [-o 输出.zip] [--force]
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pack_common import (  # noqa: E402
    JUNK_DIRS,
    JUNK_NAMES,
    configure_stdout,
    human_size,
)


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="把大肥鱼资料包目录打成 zip（根目录直接是 manifest.json）。")
    parser.add_argument("pack", help="资料包目录")
    parser.add_argument("-o", "--out", help="输出 zip 路径，默认 <资料包目录名>.zip")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的 zip")
    args = parser.parse_args(argv)

    pack_dir = Path(args.pack).resolve()
    if not pack_dir.is_dir():
        print(f"[错误] 资料包目录不存在：{pack_dir}", file=sys.stderr)
        return 1
    if not (pack_dir / "manifest.json").is_file():
        print(f"[错误] {pack_dir} 下没有 manifest.json，不像资料包目录；先运行 build_pack.py 或确认路径", file=sys.stderr)
        return 1
    out_path = Path(args.out).resolve() if args.out else pack_dir.with_suffix(".zip")
    if out_path.exists() and not args.force:
        print(f"[错误] 输出文件已存在：{out_path}；确认覆盖请加 --force", file=sys.stderr)
        return 1

    entries: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(pack_dir):
        dirnames[:] = sorted(name for name in dirnames if name not in JUNK_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or name in JUNK_NAMES or name.startswith("._"):
                continue
            entries.append(path)
    if not entries:
        print(f"[错误] 资料包目录为空：{pack_dir}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in entries:
                archive.write(path, path.relative_to(pack_dir).as_posix())
    except OSError as exc:
        print(f"[错误] 写 zip 失败：{exc}", file=sys.stderr)
        return 1

    size = out_path.stat().st_size
    print(f"[完成] 资料包 zip：{out_path}")
    print(f"  文件 {len(entries)} 个，压缩后 {human_size(size)}")
    print("导入：Umi Claw「大肥鱼 → 资料包 → 导入 zip」（导入前应用会自动整包备份）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
