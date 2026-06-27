#!/usr/bin/env node
// Assemble the per-page/per-viewport PNGs produced by the visual-preview
// Playwright suite into a single browsable gallery (`index.html`) plus a
// Markdown summary (`summary.md`) suitable for a GitHub job summary / PR
// comment.
//
// Layout consumed:  visual-snapshots/<project>/<slug>.png
// Outputs:          visual-snapshots/index.html
//                   visual-snapshots/summary.md
//
// Pure Node, no deps. Run after `npm run visual`:  node scripts/build-visual-gallery.mjs
import { existsSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = "visual-snapshots";

// Stable, friendly ordering + labels for known projects (viewports). Unknown
// projects still render, appended in discovery order.
const PROJECT_LABELS = {
  "public-desktop": "Desktop",
  "app-desktop": "Desktop",
  "public-mobile": "Mobile",
  "app-mobile": "Mobile",
};
const PROJECT_ORDER = ["public-desktop", "app-desktop", "public-mobile", "app-mobile"];

function titleFromSlug(slug) {
  return slug.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function discover() {
  if (!existsSync(ROOT)) return { pages: new Map(), projects: [] };
  const projects = readdirSync(ROOT).filter((name) => {
    if (name.startsWith(".")) return false; // skip .pw-output
    return statSync(join(ROOT, name)).isDirectory();
  });

  // page slug -> Map(project -> relative png path)
  const pages = new Map();
  for (const project of projects) {
    const dir = join(ROOT, project);
    for (const file of readdirSync(dir)) {
      if (!file.endsWith(".png")) continue;
      const slug = file.replace(/\.png$/, "");
      if (!pages.has(slug)) pages.set(slug, new Map());
      pages.get(slug).set(project, `${project}/${file}`);
    }
  }

  const orderedProjects = [
    ...PROJECT_ORDER.filter((p) => projects.includes(p)),
    ...projects.filter((p) => !PROJECT_ORDER.includes(p)),
  ];
  return { pages, projects: orderedProjects };
}

function uniqueViewports(projects) {
  const seen = new Map();
  for (const p of projects) {
    const label = PROJECT_LABELS[p] ?? titleFromSlug(p);
    if (!seen.has(label)) seen.set(label, p);
  }
  return [...seen.keys()];
}

function buildHtml(pages, projects) {
  const cards = [...pages.entries()]
    .map(([slug, byProject]) => {
      const shots = projects
        .filter((p) => byProject.has(p))
        .map((p) => {
          const label = PROJECT_LABELS[p] ?? titleFromSlug(p);
          const src = byProject.get(p);
          return `
          <figure class="shot">
            <figcaption>${label}<span class="proj">${p}</span></figcaption>
            <a href="${src}" target="_blank" rel="noopener"><img loading="lazy" src="${src}" alt="${slug} — ${label}"></a>
          </figure>`;
        })
        .join("");
      return `
      <section class="page" id="${slug}">
        <h2>${titleFromSlug(slug)}</h2>
        <div class="shots">${shots}</div>
      </section>`;
    })
    .join("");

  const nav = [...pages.keys()]
    .map((slug) => `<a href="#${slug}">${titleFromSlug(slug)}</a>`)
    .join("");

  const stamp = new Date().toISOString().replace("T", " ").slice(0, 16) + " UTC";

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visual preview · The Tribunal</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; background: #0b0b0c; color: #e7e7ea; }
  header { position: sticky; top: 0; z-index: 5; backdrop-filter: blur(8px); background: rgba(11,11,12,.8); border-bottom: 1px solid #26262b; padding: 14px 20px; }
  header h1 { margin: 0; font-size: 16px; letter-spacing: .2px; }
  header .meta { color: #9a9aa3; font-size: 12px; margin-top: 2px; }
  nav { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 20px; border-bottom: 1px solid #26262b; }
  nav a { font-size: 12px; color: #cfcfd6; text-decoration: none; padding: 3px 9px; border: 1px solid #303036; border-radius: 999px; }
  nav a:hover { background: #1a1a1e; }
  main { padding: 8px 20px 64px; }
  .page { padding: 22px 0; border-bottom: 1px solid #1d1d21; }
  .page h2 { font-size: 15px; margin: 0 0 12px; color: #fbe36b; }
  .shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  figure.shot { margin: 0; background: #131316; border: 1px solid #26262b; border-radius: 10px; overflow: hidden; }
  figcaption { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #c9c9d1; padding: 8px 12px; border-bottom: 1px solid #26262b; }
  figcaption .proj { color: #74747e; font-size: 11px; }
  figure.shot img { display: block; width: 100%; height: auto; background: #fff; }
</style>
</head>
<body>
<header>
  <h1>Visual preview — The Tribunal</h1>
  <div class="meta">${pages.size} page(s) · ${projects.length} viewport project(s) · generated ${stamp}</div>
</header>
<nav>${nav}</nav>
<main>${cards || "<p>No screenshots were captured.</p>"}</main>
</body>
</html>`;
}

function buildSummary(pages, projects) {
  const viewports = uniqueViewports(projects);
  const header = `| Page | ${viewports.join(" | ")} |`;
  const divider = `| --- | ${viewports.map(() => ":---:").join(" | ")} |`;
  const rows = [...pages.entries()].map(([slug, byProject]) => {
    const cells = viewports.map((label) => {
      const captured = projects.some(
        (p) => (PROJECT_LABELS[p] ?? titleFromSlug(p)) === label && byProject.has(p),
      );
      return captured ? "✅" : "—";
    });
    return `| ${titleFromSlug(slug)} | ${cells.join(" | ")} |`;
  });

  const total = [...pages.values()].reduce((n, m) => n + m.size, 0);
  return [
    "## 📸 Visual preview",
    "",
    `Captured **${total} screenshot(s)** across **${pages.size} page(s)** and **${viewports.length} viewport(s)**.`,
    "",
    header,
    divider,
    ...rows,
    "",
    "> Open the **`visual-gallery`** artifact (`index.html`) to see the actual renders, or the **`visual-playwright-report`** artifact for the inline Playwright report.",
    "",
  ].join("\n");
}

const { pages, projects } = discover();
writeFileSync(join(ROOT, "index.html"), buildHtml(pages, projects));
writeFileSync(join(ROOT, "summary.md"), buildSummary(pages, projects));

const total = [...pages.values()].reduce((n, m) => n + m.size, 0);
process.stdout.write(
  `visual-gallery: ${total} screenshot(s), ${pages.size} page(s), ${projects.length} project(s) → ${ROOT}/index.html\n`,
);
if (pages.size === 0) {
  console.error("visual-gallery: no screenshots found under " + ROOT);
  process.exit(1);
}
