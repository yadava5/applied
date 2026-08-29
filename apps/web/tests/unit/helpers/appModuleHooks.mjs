/**
 * Module-resolution hooks so `node --test` can load an app module that uses the
 * `@/*` path alias, or imports JSON the way a bundler lets you.
 *
 * Registered by `helpers/appModule.mjs` — see that file for why this exists and
 * for the approach it replaces. This half runs on the loader thread and must
 * stay dependency-free.
 *
 * TWO REWRITES, BOTH NARROW:
 *
 *   1. `@/x` -> the file under `apps/web` that tsconfig's `paths` points at,
 *      probing the same extensions the bundler would.
 *   2. A resolved `.json` URL gets `type: "json"` added to its import
 *      attributes. Node requires the attribute at the import site; bundlers do
 *      not, so `lib/demo/rulesLayer.ts`'s `import rulesRaw from "./rules.json"`
 *      is legal in the app and `ERR_IMPORT_ATTRIBUTE_MISSING` under plain Node.
 *      Supplying it here changes no semantics: JSON is the only thing that
 *      module could have been asking for.
 *
 * Everything else falls through to Node, including type-stripping `.ts`.
 */
import { existsSync, statSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** `apps/web` — what the `@/*` alias in tsconfig.json points at. This file
 *  sits at `tests/unit/helpers/`, so the app root is three levels up. */
const WEB_ROOT = resolvePath(fileURLToPath(import.meta.url), "../../../..");

/** Extensions to probe, in the order the bundler would. */
const CANDIDATES = ["", ".ts", ".tsx", ".mjs", ".js", "/index.ts", "/index.tsx"];

function isFile(path) {
  return existsSync(path) && statSync(path).isFile();
}

export async function resolve(specifier, context, nextResolve) {
  let spec = specifier;
  if (spec.startsWith("@/")) {
    const base = resolvePath(WEB_ROOT, spec.slice(2));
    const hit = CANDIDATES.map((ext) => base + ext).find(isFile);
    if (hit === undefined) {
      throw new Error(`appModuleHooks: cannot resolve "${specifier}" under ${WEB_ROOT}`);
    }
    spec = pathToFileURL(hit).href;
  }
  const resolved = await nextResolve(spec, context);
  if (!resolved.url.endsWith(".json")) return resolved;
  return { ...resolved, importAttributes: { ...resolved.importAttributes, type: "json" } };
}
