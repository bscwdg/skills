---
name: ppt-builder-skill
description: 根据主题生成原生 .pptx 演示文稿。用户要求制作 PPT、生成幻灯片、做演示文稿、写一个汇报、make a slide deck 或 build a PowerPoint file 时使用。通过内置 Node 脚本生成真实 .pptx 文件，并支持 default、dark、corporate 等预设主题。
---

# PPT Builder Skill

Use this skill to turn a topic into a native `.pptx` deck that opens in PowerPoint / WPS / Keynote.

## Workflow

1. Clarify the request: topic, audience, approximate slide count, language (default Chinese), and visual theme (`default` / `dark` / `corporate`).
2. Draft an outline: for each slide decide a `layout` and a short title plus key points. Present the outline to the user and ask for confirmation or edits before generating content.
3. After the outline is confirmed, write a JSON spec file following `references/slide-spec.md`. Cover the deck with `title`, `bullets`, `section`, `two-column`, and `quote` layouts as appropriate. Put speaker-only material in each slide's `notes`.
4. On first use, install the dependency inside the skill directory:

   ```bash
   cd "$SKILL_DIR" && npm install
   ```

   On Windows CMD:

   ```cmd
   cd "%SKILL_DIR%" && npm install
   ```

5. Generate the deck:

   ```bash
   node "$SKILL_DIR/scripts/build_pptx.js" <spec.json> -o <output.pptx>
   ```

   On Windows CMD:

   ```cmd
   node "%SKILL_DIR%\scripts\build_pptx.js" <spec.json> -o <output.pptx>
   ```

   `--theme` overrides the spec's theme. If `-o` is omitted, the output path mirrors the spec name with a `.pptx` extension. On success the script prints the absolute output path.

6. Report the generated `.pptx` absolute path and note it can be opened in PowerPoint / WPS / Keynote.

## Spec Reference

Read `references/slide-spec.md` for the full JSON schema, layout field tables, theme definitions, and an end-to-end example before writing the spec.

## Output Rules

- Do not fabricate facts; fill slides from the user's topic and confirmed outline only.
- Keep one slide's bullets to ≤6 items and ≤30 characters each; split into more slides rather than crowding.
- Use `section` pages to break the deck into 3–5 segments.
- Speaker-only explanation goes into `notes`, not onto the visible slide.
- If the user did not specify a theme, use `default`.
- Always write the JSON spec to a file before running the script; never pipe untrusted inline JSON.
