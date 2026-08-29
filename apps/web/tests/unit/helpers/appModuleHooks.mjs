/**
 * Module-resolution hooks so `node --test` can load an app module that uses the
 * `@/*` path alias, imports JSON the way a bundler lets you, or is written in
 * JSX.
 *
 * Registered by `helpers/appModule.mjs` — see that file for why this exists and
 * for the approach it replaces. This half runs on the loader thread; its only
 * dependency is `typescript`, which is already what `pnpm typecheck` runs.
 *
 * THE REWRITES, ALL NARROW:
 *
 *   1. `@/x` -> the file under `apps/web` that tsconfig's `paths` points at,
 *      probing the same extensions the bundler would.
 *   2. A relative specifier with no extension gets the same probe. Bundlers
 *      resolve `./foo` to `foo.ts`; Node does not, and a component graph is
 *      full of them.
 *   3. `next/link` -> `next/link.js`. Next ships those entry points as plain
 *      files and expects a bundler to add the extension; Node ESM will not.
 *      Only the single-segment, extensionless `next/x` form is touched.
 *   4. A resolved `.json` URL gets `type: "json"` added to its import
 *      attributes. Node requires the attribute at the import site; bundlers do
 *      not, so `lib/demo/rulesLayer.ts`'s `import rulesRaw from "./rules.json"`
 *      is legal in the app and `ERR_IMPORT_ATTRIBUTE_MISSING` under plain Node.
 *      Supplying it here changes no semantics: JSON is the only thing that
 *      module could have been asking for.
 *   5. A `.tsx` file is transpiled with the TypeScript compiler API before Node
 *      sees it. Node strips types from `.ts` natively and refuses `.tsx`
 *      outright (`ERR_UNKNOWN_FILE_EXTENSION`), which is what kept every
 *      component in this app out of the unit suite.
 *
 * WHY (5) IS A LOAD HOOK AND NOT A TRANSPILE-AND-IMPORT-A-DATA-URL.
 * `helpers/renderTsx.mjs` does the latter and can only ever do the ENTRY
 * module, so it renders leaf components whose own imports Node can already
 * resolve. A hook applies to every module in the graph, which is what it takes
 * to load a component that mounts another component — and mounting is where
 * this app's questions actually get asked or not asked.
 *
 * Everything else falls through to Node.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

/** `apps/web` — what the `@/*` alias in tsconfig.json points at. This file
 *  sits at `tests/unit/helpers/`, so the app root is three levels up. */
const WEB_ROOT = resolvePath(fileURLToPath(import.meta.url), "../../../..");

/** Extensions to probe, in the order the bundler would. */
const CANDIDATES = ["", ".ts", ".tsx", ".mjs", ".js", "/index.ts", "/index.tsx"];

function isFile(path) {
  return existsSync(path) && statSync(path).isFile();
}

function probe(base) {
  return CANDIDATES.map((ext) => base + ext).find(isFile);
}

export async function resolve(specifier, context, nextResolve) {
  let spec = specifier;
  if (spec.startsWith("@/")) {
    const hit = probe(resolvePath(WEB_ROOT, spec.slice(2)));
    if (hit === undefined) {
      throw new Error(`appModuleHooks: cannot resolve "${specifier}" under ${WEB_ROOT}`);
    }
    spec = pathToFileURL(hit).href;
  } else if (spec.startsWith(".") && context.parentURL?.startsWith("file:")) {
    // Left alone when nothing matches: a relative specifier Node CAN resolve
    // (or genuinely cannot) should fail with Node's own message, not this
    // file's.
    const hit = probe(resolvePath(dirname(fileURLToPath(context.parentURL)), spec));
    if (hit !== undefined) spec = pathToFileURL(hit).href;
  } else if (/^next\/[a-z-]+$/.test(spec)) {
    spec = `${spec}.js`;
  }
  const resolved = await nextResolve(spec, context);
  if (!resolved.url.endsWith(".json")) return resolved;
  return { ...resolved, importAttributes: { ...resolved.importAttributes, type: "json" } };
}

export async function load(url, context, nextLoad) {
  if (!url.endsWith(".tsx")) return nextLoad(url, context);
  const path = fileURLToPath(url);
  const { outputText } = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  });
  return { format: "module", shortCircuit: true, source: outputText };
}
