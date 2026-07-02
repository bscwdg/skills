#!/usr/bin/env python3
"""Quick structural inspector for a Codex skill folder."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def parse_simple_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, ["SKILL.md must start with YAML frontmatter delimited by ---"]

    data: dict[str, str] = {}
    errors: list[str] = []
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            errors.append(f"Invalid frontmatter line: {line}")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        data[key] = value
    return data, errors


def inspect_skill(path: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists() or not path.is_dir():
        print(f"ERROR: Not a directory: {path}")
        return 2

    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        print("ERROR: Missing SKILL.md")
        return 2

    text = skill_md.read_text(encoding="utf-8")
    frontmatter, parse_errors = parse_simple_frontmatter(text)
    errors.extend(parse_errors)

    allowed_keys = {"name", "description"}
    extra_keys = set(frontmatter) - allowed_keys
    missing_keys = allowed_keys - set(frontmatter)
    if extra_keys:
        errors.append(f"Frontmatter has unsupported keys: {', '.join(sorted(extra_keys))}")
    if missing_keys:
        errors.append(f"Frontmatter is missing keys: {', '.join(sorted(missing_keys))}")

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if name and path.name != name:
        errors.append(f"Folder name '{path.name}' does not match frontmatter name '{name}'")
    if name and not NAME_RE.match(name):
        errors.append("Skill name must use lowercase letters, digits, and hyphens only")
    if description and len(description) < 80:
        warnings.append("Description may be too short to trigger reliably")
    if "[TODO" in text or "TODO:" in text:
        errors.append("SKILL.md still contains TODO placeholders")

    openai_yaml = path / "agents" / "openai.yaml"
    if openai_yaml.exists():
        yaml_text = openai_yaml.read_text(encoding="utf-8")
        if name and f"${name}" not in yaml_text:
            warnings.append("agents/openai.yaml default_prompt should mention the skill as $skill-name")
    else:
        warnings.append("Missing agents/openai.yaml UI metadata")

    for resource_name in ("scripts", "references", "assets"):
        resource_dir = path / resource_name
        if resource_dir.exists() and any(resource_dir.iterdir()) and resource_name not in text:
            warnings.append(f"{resource_name}/ has content but is not mentioned in SKILL.md")

    if errors:
        print("FAILED")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARN: {item}")
        return 1

    print("PASSED")
    for item in warnings:
        print(f"WARN: {item}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a Codex skill folder.")
    parser.add_argument("path", type=Path, help="Path to the skill folder")
    args = parser.parse_args()
    return inspect_skill(args.path)


if __name__ == "__main__":
    sys.exit(main())
