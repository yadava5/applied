/**
 * Render a `.tsx` component to static markup under plain `node --test`.
 *
 * WHY THIS EXISTS. Every other unit test here imports a `.ts` module, which
 * Node type-strips natively. `.tsx` it cannot parse at all
 * (`ERR_UNKNOWN_FILE_EXTENSION`), so a presentation decision — "does this row
 * draw a preview? does it draw a link?" — had no executable coverage and was
 * asserted only by reading the file. `typescript` is already a devDependency
 * (it is what `pnpm typecheck` runs), so this needs nothing new installed.
 *
 * HOW. The component's source is transpiled with the TypeScript compiler API,
 * every import specifier in the OUTPUT is rewritten to an absolute URL (`@/…`
 * against the app root, bare names through `import.meta.resolve`), and the
 * result is imported as a data: URL. Rewriting is what makes a data: URL
 * viable — bare and aliased specifiers cannot be resolved from one otherwise.
 *
 * WHAT IT DELIBERATELY IS NOT. Only the ENTRY module is rewritten, so this
 * renders leaf presentational components whose own imports Node can already
 * resolve. It is not a Next.js environment: a component reaching for
 * `next/link`, `next/navigation` or a hook that needs a browser will not load,
 * and adding stubs to make one load would be building a second, worse renderer
 * next to the real one. Those surfaces belong to Playwright.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

/** `apps/web` — what the `@/*` path alias in tsconfig.json points at. This
 *  file sits at `tests/unit/helpers/`, so the app root is three levels up. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../../..");

/** Extensions to probe, in the order the bundler would. */
const CANDIDATES = [".ts", ".tsx", ".mjs", ".js", "/index.ts", "/index.tsx"];

function probe(base) {
  for (const ext of CANDIDATES) if (existsSync(base + ext)) return base + ext;
  return existsSync(base) ? base : null;
}

function absoluteSpecifier(spec, fromDir) {
  const base = spec.startsWith("@/")
    ? resolvePath(WEB_ROOT, spec.slice(2))
    : spec.startsWith(".")
      ? resolvePath(fromDir, spec)
      : null;
  if (base === null) return import.meta.resolve(spec); // bare: react, lucide-react…
  const hit = probe(base);
  if (hit === null) throw new Error(`renderTsx: cannot resolve "${spec}" from ${fromDir}`);
  return pathToFileURL(hit).href;
}

/** Import a `.tsx` module by path relative to `apps/web`. */
export async function importTsx(relativePath) {
  const absolute = resolvePath(WEB_ROOT, relativePath);
  const { outputText } = ts.transpileModule(readFileSync(absolute, "utf8"), {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absolute,
  });
  const rewritten = outputText.replace(
    /(\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g,
    (_match, head, spec) => `${head}"${absoluteSpecifier(spec, dirname(absolute))}"`,
  );
  const encoded = Buffer.from(rewritten).toString("base64");
  return import(`data:text/javascript;base64,${encoded}`);
}

/** The component's markup for these props — `""` when it renders nothing. */
export function markup(element) {
  return renderToStaticMarkup(element);
}

/** Read a source file from `apps/web`, for structural (wiring) assertions. */
export function readSource(relativePath) {
  return readFileSync(resolvePath(WEB_ROOT, relativePath), "utf8");
}
