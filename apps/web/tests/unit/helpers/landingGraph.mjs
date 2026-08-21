/**
 * The landing pages' real import graph, comments stripped.
 *
 * Lifted out of `landing-variants.test.mjs` on 2026-08-21 so the voice gates
 * (`landing-voice.test.mjs`) could hold the same set of modules. The two
 * files ask different questions of one graph, and a second hand-rolled
 * walker would drift from this one the first time a page moved — which is
 * the failure this repo keeps rediscovering: a scan that quietly stops
 * covering the surface it names.
 *
 * WHY A SOURCE SCAN AT ALL. These are components the unit harness cannot
 * render, and the failures worth catching are one line each: a board mounted
 * without its transport prop, a dash in a rendered string, a model name in a
 * caption.
 *
 * COMMENTS ARE STRIPPED BEFORE ANYTHING SEES THE SOURCE, and that is
 * load-bearing rather than tidy. Every consumer of this module scans for
 * things the docblocks in those same files QUOTE VERBATIM — `DECISION.rulesF1`,
 * em dashes, "SetFit". A raw-source scan would go red on the note explaining
 * why the thing was removed, and, worse, would stay green when a render was
 * deleted and its comment left behind.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

export const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

/** The shipping landing, first — `/landing-b` was promoted to `app/page.tsx`. */
export const ROOT_PAGE = join(webRoot, "app", "page.tsx");

/** The preserved comparison set, which stays noindex on its own routes. */
export const CANDIDATE_PAGES = ["landing-a", "landing-c"].map((dir) =>
  join(webRoot, "app", dir, "page.tsx"),
);

export const PAGES = [ROOT_PAGE, ...CANDIDATE_PAGES];

/** Comments out, code only. `{/* … *\/}` JSX comments go with them: the inner
 *  block matches the same rule, which leaves an inert `{}`. */
export function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/** `import x from "y"`, `export … from "y"`, and dynamic `import("y")`. */
function importSpecs(src) {
  return [...src.matchAll(/(?:from|import)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1]);
}

function resolveSpec(spec, fromDir) {
  const base = spec.startsWith("@/")
    ? join(webRoot, spec.slice(2))
    : spec.startsWith(".")
      ? join(fromDir, spec)
      : null;
  if (!base) return null; // a package — not ours to walk
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** Every repo module reachable from the candidate pages, path → stripped code. */
export function walkGraph() {
  const seen = new Map();
  const queue = [...PAGES];
  while (queue.length > 0) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    const src = readFileSync(file, "utf8");
    seen.set(file, code(src));
    if (!/\.(ts|tsx)$/.test(file)) continue; // json/css carry no imports
    for (const spec of importSpecs(src)) {
      const resolved = resolveSpec(spec, dirname(file));
      if (resolved && !seen.has(resolved)) queue.push(resolved);
    }
  }
  return seen;
}

export const rel = (file) => relative(webRoot, file);

/** `app/page.tsx` is named exactly: the promoted landing is a landing module,
 *  and the `app/landing-` prefix does not reach it. Miss this and the
 *  strongest assertion in this suite — no landing module names the live
 *  transport — silently stops covering the page a stranger actually loads. */
export const isLandingModule = (file) =>
  rel(file) === "app/page.tsx" ||
  rel(file).startsWith("app/landing-") ||
  rel(file).startsWith("components/marketing/");

export const marketing = (name) => join(webRoot, "components", "marketing", name);
