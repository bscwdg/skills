# Skill Quality Checklist

## Trigger Design

- The `description` explains both capability and trigger conditions.
- The trigger mentions concrete tasks, file types, tools, or contexts.
- The description is specific enough to avoid firing on unrelated work.
- The skill name is lowercase hyphen-case and matches the folder name.

## SKILL.md Body

- The body starts with the shortest useful workflow.
- Instructions are actionable and written for another Codex instance.
- The skill avoids restating generic reasoning, coding, or writing advice.
- Detailed optional material is moved to `references/`.
- Commands and scripts are shown exactly when precision matters.
- References are one level deep from `SKILL.md`.

## Resource Placement

- Put repeated deterministic operations in `scripts/`.
- Put domain knowledge, schemas, examples, and detailed variants in `references/`.
- Put templates, images, fonts, boilerplate projects, and reusable output files in `assets/`.
- Remove unused resource folders only when they are empty and not intentionally reserved.
- Do not duplicate the same guidance in both `SKILL.md` and a reference file.

## Interface Metadata

- `agents/openai.yaml` uses quoted string values.
- `interface.display_name` is human-facing and concise.
- `interface.short_description` is short enough for a UI chip.
- `interface.default_prompt` explicitly mentions `$skill-name`.
- Optional icon or brand fields are present only when the user supplied or requested them.

## Validation

- No TODO placeholders remain.
- Frontmatter contains only `name` and `description`.
- YAML frontmatter is closed with a second `---`.
- Required scripts run successfully on a representative sample.
- The official validator passes when available.
- Forward-test complex skills with realistic prompts when practical.

## Common Fixes

- If a skill is too broad, split trigger conditions or move variant-specific material to references.
- If a skill is too long, keep the workflow in `SKILL.md` and link to targeted reference files.
- If a skill is fragile, add a script rather than asking Codex to rewrite the same logic.
- If a skill triggers too often, narrow the description with explicit "Use when..." language.
- If a skill does not trigger, add concrete task phrases and artifact names to the description.
