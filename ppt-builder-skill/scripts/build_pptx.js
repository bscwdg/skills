#!/usr/bin/env node
/**
 * build_pptx.js — 读取 JSON slide spec，生成原生 .pptx 文件。
 *
 * 用法：
 *   node build_pptx.js <spec.json> [-o output.pptx] [--theme default|dark|corporate]
 *
 * spec schema 详见 references/slide-spec.md。
 */

"use strict";

const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// 主题定义
// ---------------------------------------------------------------------------
const THEMES = {
  default: {
    background: "FFFFFF",
    titleColor: "1F3A5F",
    bodyColor: "333333",
    accentColor: "2E75B6",
    mutedColor: "8C8C8C",
    titleFont: "Microsoft YaHei",
    bodyFont: "Microsoft YaHei",
  },
  dark: {
    background: "1A1A1A",
    titleColor: "FFFFFF",
    bodyColor: "D9D9D9",
    accentColor: "4FC3F7",
    mutedColor: "9E9E9E",
    titleFont: "Microsoft YaHei",
    bodyFont: "Microsoft YaHei",
  },
  corporate: {
    background: "F5F5F5",
    titleColor: "2C2C2C",
    bodyColor: "404040",
    accentColor: "E07B00",
    mutedColor: "8C8C8C",
    titleFont: "Microsoft YaHei",
    bodyFont: "Microsoft YaHei",
  },
};

// 16:9 宽屏画布尺寸（英寸）
const LAYOUT = { name: "WIDE", width: 13.333, height: 7.5 };

// ---------------------------------------------------------------------------
// CLI 解析
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const args = { spec: null, output: null, theme: null, _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-o" || a === "--output") {
      args.output = argv[++i];
    } else if (a === "--theme") {
      args.theme = argv[++i];
    } else if (a === "-h" || a === "--help") {
      printHelp();
      process.exit(0);
    } else {
      args._.push(a);
    }
  }
  args.spec = args._[0] || null;
  return args;
}

function printHelp() {
  console.error(
    "用法: node build_pptx.js <spec.json> [-o output.pptx] [--theme default|dark|corporate]"
  );
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------
function normalizeBullets(items) {
  // 接受字符串数组或 {text, level} 对象数组，统一返回 pptxgenjs text 对象数组
  if (!Array.isArray(items)) return [];
  return items.map((item) => {
    if (typeof item === "string") {
      return { text: item, options: { bullet: true, indentLevel: 0 } };
    }
    const level = Number.isFinite(item.level) ? item.level : 0;
    return {
      text: String(item.text ?? ""),
      options: { bullet: true, indentLevel: level },
    };
  });
}

function defaultOutput(specPath) {
  const ext = path.extname(specPath);
  const base = path.basename(specPath, ext);
  return path.join(path.dirname(specPath), `${base}.pptx`);
}

// ---------------------------------------------------------------------------
// 各 layout 渲染
// ---------------------------------------------------------------------------
function addTitleSlide(pptx, slide, spec, theme) {
  slide.background = { color: theme.background };

  // 顶部强调色装饰条
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: LAYOUT.width,
    h: 0.35,
    fill: { color: theme.accentColor },
    line: { type: "none" },
  });

  slide.addText(spec.title || "未命名演示", {
    x: 0.8,
    y: 2.4,
    w: LAYOUT.width - 1.6,
    h: 1.6,
    fontSize: 40,
    bold: true,
    color: theme.titleColor,
    fontFace: theme.titleFont,
    align: "left",
    valign: "middle",
  });

  if (spec.subtitle) {
    slide.addText(spec.subtitle, {
      x: 0.8,
      y: 4.0,
      w: LAYOUT.width - 1.6,
      h: 0.8,
      fontSize: 22,
      color: theme.mutedColor,
      fontFace: theme.bodyFont,
      align: "left",
    });
  }

  if (spec.author) {
    slide.addText(spec.author, {
      x: 0.8,
      y: 6.4,
      w: LAYOUT.width - 1.6,
      h: 0.5,
      fontSize: 14,
      color: theme.mutedColor,
      fontFace: theme.bodyFont,
      align: "left",
    });
  }
}

function addBulletsSlide(pptx, slide, s, theme) {
  slide.background = { color: theme.background };
  renderTitleBar(pptx, slide, s.title, theme);

  const bullets = normalizeBullets(s.bullets);
  if (bullets.length) {
    slide.addText(bullets, {
      x: 0.8,
      y: 1.7,
      w: LAYOUT.width - 1.6,
      h: LAYOUT.height - 2.3,
      fontSize: 20,
      color: theme.bodyColor,
      fontFace: theme.bodyFont,
      align: "left",
      valign: "top",
      lineSpacingMultiple: 1.2,
      paraSpaceAfter: 8,
    });
  }

  if (s.notes) slide.addNotes(s.notes);
}

function addSectionSlide(pptx, slide, s, theme) {
  slide.background = { color: theme.accentColor };

  slide.addText(s.title || "", {
    x: 0.8,
    y: 2.8,
    w: LAYOUT.width - 1.6,
    h: 1.8,
    fontSize: 44,
    bold: true,
    color: "FFFFFF",
    fontFace: theme.titleFont,
    align: "left",
    valign: "middle",
  });

  if (s.subtitle) {
    slide.addText(s.subtitle, {
      x: 0.8,
      y: 4.6,
      w: LAYOUT.width - 1.6,
      h: 0.8,
      fontSize: 20,
      color: "FFFFFF",
      fontFace: theme.bodyFont,
      align: "left",
      transparency: 20,
    });
  }
}

function addTwoColumnSlide(pptx, slide, s, theme) {
  slide.background = { color: theme.background };
  renderTitleBar(pptx, slide, s.title, theme);

  const cols = Array.isArray(s.columns) ? s.columns : [[], []];
  const left = cols[0] || [];
  const right = cols[1] || [];
  const colW = (LAYOUT.width - 1.6 - 0.6) / 2; // 左右各一，中间留 0.6 间距

  const colOpts = (extra) => ({
    x: 0,
    y: 0,
    w: colW,
    h: LAYOUT.height - 2.3,
    fontSize: 18,
    color: theme.bodyColor,
    fontFace: theme.bodyFont,
    align: "left",
    valign: "top",
    lineSpacingMultiple: 1.2,
    paraSpaceAfter: 6,
    ...extra,
  });

  // 左列
  slide.addText(normalizeBullets(left), colOpts({ x: 0.8, y: 1.7 }));
  // 右列
  slide.addText(normalizeBullets(right), colOpts({ x: 0.8 + colW + 0.6, y: 1.7 }));

  if (s.notes) slide.addNotes(s.notes);
}

function addQuoteSlide(pptx, slide, s, theme) {
  slide.background = { color: theme.background };

  // 大引号装饰
  slide.addText("“", {
    x: 0.5,
    y: 0.6,
    w: 2,
    h: 2,
    fontSize: 120,
    color: theme.accentColor,
    fontFace: theme.titleFont,
    align: "left",
    valign: "top",
    bold: true,
  });

  slide.addText(s.quote || "", {
    x: 1.6,
    y: 2.4,
    w: LAYOUT.width - 3.2,
    h: 2.6,
    fontSize: 28,
    italic: true,
    color: theme.titleColor,
    fontFace: theme.titleFont,
    align: "left",
    valign: "middle",
    lineSpacingMultiple: 1.3,
  });

  if (s.author) {
    slide.addText(`— ${s.author}`, {
      x: 1.6,
      y: 5.2,
      w: LAYOUT.width - 3.2,
      h: 0.6,
      fontSize: 18,
      color: theme.mutedColor,
      fontFace: theme.bodyFont,
      align: "left",
    });
  }

  if (s.notes) slide.addNotes(s.notes);
}

// 标准内容页顶部：标题 + 强调色下划线
function renderTitleBar(pptx, slide, title, theme) {
  slide.addText(title || "", {
    x: 0.8,
    y: 0.5,
    w: LAYOUT.width - 1.6,
    h: 0.9,
    fontSize: 30,
    bold: true,
    color: theme.titleColor,
    fontFace: theme.titleFont,
    align: "left",
    valign: "middle",
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.8,
    y: 1.45,
    w: 1.6,
    h: 0.06,
    fill: { color: theme.accentColor },
    line: { type: "none" },
  });
}

const LAYOUT_RENDERERS = {
  title: addTitleSlide,
  bullets: addBulletsSlide,
  section: addSectionSlide,
  "two-column": addTwoColumnSlide,
  quote: addQuoteSlide,
};

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.spec) {
    printHelp();
    process.exit(2);
  }

  const specPath = path.resolve(args.spec);
  let specRaw;
  try {
    specRaw = fs.readFileSync(specPath, "utf8");
  } catch (e) {
    console.error(`ERROR: 无法读取 spec 文件: ${specPath} (${e.message})`);
    process.exit(2);
  }

  let spec;
  try {
    spec = JSON.parse(specRaw);
  } catch (e) {
    console.error(`ERROR: spec JSON 解析失败: ${e.message}`);
    process.exit(2);
  }

  const themeName = args.theme || spec.theme || "default";
  const theme = THEMES[themeName];
  if (!theme) {
    console.error(
      `ERROR: 未知主题 '${themeName}'，可选: ${Object.keys(THEMES).join(", ")}`
    );
    process.exit(2);
  }

  const pptxgenjs = require("pptxgenjs");
  const pptx = new pptxgenjs();
  pptx.defineLayout(LAYOUT);
  pptx.layout = LAYOUT.name;
  pptx.author = spec.author || "PPT Builder Skill";
  pptx.title = spec.title || "Presentation";
  pptx.subject = spec.subtitle || "";

  const slides = Array.isArray(spec.slides) ? spec.slides : [];
  if (slides.length === 0) {
    console.error("WARN: spec.slides 为空，将生成一份空演示文稿");
  }

  slides.forEach((s, idx) => {
    const layout = (s && s.layout) || "bullets";
    const renderer = LAYOUT_RENDERERS[layout];
    const slide = pptx.addSlide();
    if (!renderer) {
      console.error(
        `WARN: 第 ${idx + 1} 页未知 layout '${layout}'，跳过渲染`
      );
      return;
    }
    renderer(pptx, slide, s || {}, theme);
  });

  const outFile = path.resolve(args.output || defaultOutput(specPath));
  await pptx.writeFile({ fileName: outFile });
  console.log(outFile);
}

main().catch((e) => {
  console.error(`ERROR: ${e && e.message ? e.message : e}`);
  process.exit(1);
});
