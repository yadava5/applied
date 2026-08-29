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
 * `next/link`, `next/navigation` or a hook that needs a browser will not load.
 *
 * THE ONE THING THAT CHANGED, AND WHERE THE LINE STILL IS (#518 gap-fix).
 * `importTsx` now takes an optional `stubs` map, specifier -> module URL, and
 * `stubModule` builds such a URL from a plain object. It substitutes ONE named
 * import of the entry module; it does not simulate Next, a browser or a router.
 *
 * The paragraph this replaces said "adding stubs to make one load would be
 * building a second, worse renderer". That is still true of stubbing a
 * *renderer* — `next/link`, `next/navigation`, a DOM. It is not true of
 * substituting a module the unit under test only reads a VALUE from: the
 * component's own body still executes, real React still builds the element and
 * real `react-dom/server` still renders it. The distinction that keeps this
 * honest is that a stub must be an INPUT to the code under test (a clock, a
 * fetch, an API client), never a stand-in for the code under test itself.
 *
 * `helpers/clientHarness.mjs` is the one place that stubs `react`, and its
 * docstring states what that costs.
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

/**
 * A bare specifier, resolved and then CHECKED TO EXIST.
 *
 * `import.meta.resolve` answers for a package without an `exports` map by
 * joining the path, and it does not stat the result: `next/server` resolves to
 * `node_modules/next/server`, which is a directory entry that is not there —
 * the real module is `next/server.js`. The failure surfaces much later as
 * `ERR_MODULE_NOT_FOUND` on a data: URL, with no clue which specifier caused
 * it, so the same extension probe the relative branch uses is applied here.
 */
function bareSpecifier(spec) {
  const resolved = import.meta.resolve(spec);
  if (!resolved.startsWith("file:")) return resolved; // node:*, data:*
  const path = fileURLToPath(resolved);
  if (existsSync(path)) return resolved;
  const hit = probe(path);
  if (hit === null) throw new Error(`renderTsx: cannot resolve bare specifier "${spec}"`);
  return pathToFileURL(hit).href;
}

function absoluteSpecifier(spec, fromDir, stubs) {
  if (stubs !== undefined && Object.hasOwn(stubs, spec)) return stubs[spec];
  const base = spec.startsWith("@/")
    ? resolvePath(WEB_ROOT, spec.slice(2))
    : spec.startsWith(".")
      ? resolvePath(fromDir, spec)
      : null;
  if (base === null) return bareSpecifier(spec); // bare: react, lucide-react…
  const hit = probe(base);
  if (hit === null) throw new Error(`renderTsx: cannot resolve "${spec}" from ${fromDir}`);
  return pathToFileURL(hit).href;
}

/** Live stub objects, keyed by the id baked into the data: URL that reads them. */
const STUB_REGISTRY = new Map();
let stubCounter = 0;

/**
 * A module URL whose named exports are this object's own properties.
 *
 * Pass the result as a value in `importTsx`'s `stubs` map. The generated module
 * reads the object out of a registry at import time rather than embedding it,
 * so the stub can be a closure the test still holds a reference to — which is
 * what makes "was this called, and with what?" answerable.
 *
 * `default` is emitted as the default export; every other key must be a plain
 * identifier, because ESM named exports are syntax and not strings.
 */
export function stubModule(exportsObject) {
  const id = `s${stubCounter++}`;
  STUB_REGISTRY.set(id, exportsObject);
  globalThis.__renderTsxStubs = STUB_REGISTRY;

  const lines = [`const m = globalThis.__renderTsxStubs.get(${JSON.stringify(id)});`];
  for (const name of Object.keys(exportsObject)) {
    if (name === "default") {
      lines.push("export default m.default;");
      continue;
    }
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) {
      throw new Error(`stubModule: "${name}" is not a legal export name`);
    }
    lines.push(`export const ${name} = m[${JSON.stringify(name)}];`);
  }
  return `data:text/javascript;base64,${Buffer.from(lines.join("\n")).toString("base64")}`;
}

/**
 * Import a `.ts`/`.tsx` module by path relative to `apps/web`.
 *
 * `stubs` maps an import specifier of THIS module — `"react"`,
 * `"@/lib/api/server"` — to a module URL, typically from `stubModule`. Every
 * other specifier resolves to the real file, so the module graph under the
 * entry is untouched.
 */
export async function importTsx(relativePath, { stubs } = {}) {
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
    (_match, head, spec) => `${head}"${absoluteSpecifier(spec, dirname(absolute), stubs)}"`,
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
