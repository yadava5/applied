/**
 * Dev-only: screenshot each .page element to scratchpad PNGs so the export-size
 * layout can be inspected page-by-page (clipping / overlap / density audit).
 * Not part of the ship pipeline. Usage: node scripts/shoot.mjs [pageNums csv]
 */
import puppeteer from "puppeteer";
import { mkdirSync } from "node:fs";

const URL = process.env.BOOKLET_URL ?? "http://localhost:5182";
// Repo-local by default. This used to point at one session's shared scratchpad,
// which meant a partial run left another project's PNGs sitting in the output
// directory under this project's filenames -- two readers were misled by that.
const OUT = process.env.SHOOT_OUT ?? new URL("../.shots", import.meta.url).pathname;
const only = process.argv[2] ? new Set(process.argv[2].split(",").map(Number)) : null;

mkdirSync(OUT, { recursive: true });
const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox", "--font-render-hinting=none"] });
const page = await browser.newPage();
await page.setViewport({ width: 840, height: 1080, deviceScaleFactor: 2 });
await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
await page.evaluate(async () => { await document.fonts.ready; });
await new Promise((r) => setTimeout(r, 400));

const handles = await page.$$(".page");
console.log(`[shoot] ${handles.length} pages`);
for (let i = 0; i < handles.length; i++) {
  const num = i + 1;
  if (only && !only.has(num)) continue;
  await handles[i].screenshot({ path: `${OUT}/p${String(num).padStart(2, "0")}.png` });
  console.log(`[shoot] p${num}`);
}
await browser.close();
