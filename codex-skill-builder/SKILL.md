---
name: codex-skill-builder
description: 创建、更新、审查和验证 Codex Skills。用户想设计新 Skill、初始化技能目录、改进现有 SKILL.md、判断内容应放入 scripts/references/assets、编写或完善 agents/openai.yaml、修复技能元数据、检查命名/frontmatter/资源结构，或把重复的 Codex 工作流沉淀为可复用 Skill 时使用。
---

# Codex Skill Builder

## Core Workflow

Follow this workflow when creating or improving a Codex skill:

1. Clarify the intended trigger and 2-4 concrete user requests the skill should handle.
2. Choose a lowercase hyphen-case skill name under 64 characters.
3. Decide the minimum resource shape:
   - Use `scripts/` for deterministic operations that would otherwise be rewritten repeatedly.
   - Use `references/` for detailed guidance, schemas, examples, policies, or variant-specific instructions.
   - Use `assets/` only for files meant to be copied or used in outputs.
4. Keep `SKILL.md` concise. Put trigger information in the YAML `description`, and put detailed optional material in referenced files.
5. Create or update `agents/openai.yaml` with user-facing interface metadata.
6. Validate the result and fix basic structure issues before declaring it done.

## Creating A Skill

When creating a new skill, prefer an initialization script if one is available in the active environment. Pass deterministic interface values:

```bash
scripts/init_skill.py <skill-name> --path <skills-dir> --resources scripts,references --interface display_name="Display Name" --interface short_description="Short description." --interface default_prompt="Use $skill-name to ..."
```

Only request resource directories that the skill actually needs. Delete placeholder files and TODO text before finishing.

## Updating A Skill

For an existing skill:

1. Read `SKILL.md` first.
2. Read `agents/openai.yaml` if present.
3. Read only the reference files that match the user's requested change.
4. Preserve unrelated user edits.
5. Keep the frontmatter limited to `name` and `description`.
6. Regenerate or edit `agents/openai.yaml` when the trigger description or purpose changes materially.

## Review Checklist

Use `references/skill-quality-checklist.md` when performing a thorough review, when a skill feels too broad, or when deciding whether content belongs in `SKILL.md`, `references/`, `scripts/`, or `assets/`.

Run the local inspector for a quick structural pass:

```bash
python scripts/inspect_skill.py <path-to-skill-folder>
```

Treat the inspector as a fast sanity check, not a replacement for judgment.

## Writing Guidance

- Write SKILL.md instructions in imperative form.
- Keep the main body short enough to load comfortably.
- Avoid generic AI advice that Codex already knows.
- Include exact commands, file paths, or decision rules only when they prevent errors.
- Reference optional files explicitly and say when to read them.
- Avoid deeply nested references.
- Do not add README, changelog, install guide, or other auxiliary docs unless the user explicitly asks.

## Validation

After edits, validate with any official validator available in the environment. If no validator is available, run `scripts/inspect_skill.py` and manually check:

- Folder name equals frontmatter `name`.
- Name uses lowercase letters, digits, and hyphens only.
- Frontmatter has exactly `name` and `description`.
- Description says both what the skill does and when to use it.
- No TODO placeholders remain.
- Bundled resources are referenced from `SKILL.md` when they are meant to be used.
