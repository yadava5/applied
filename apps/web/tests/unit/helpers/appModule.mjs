/**
 * Import an app `.ts` module under `node --test`, aliases and JSON included.
 *
 * WHY THIS EXISTS. Most unit tests here import a `.ts` module directly: Node
 * type-strips it natively and the module's own imports happen to be resolvable.
 * Two shapes are not:
 *
 *   - `lib/demo/rulesLayer.ts` does `import rulesRaw from "./rules.json"`.
 *     Plain Node refuses it with `ERR_IMPORT_ATTRIBUTE_MISSING`, which is why
 *     `tests/e2e/import.spec.ts` says the rules layer "cannot be loaded by a
 *     unit test" and asserts its behaviour through a browser instead.
 *   - `lib/demo/sampleInbox.ts` reaches `@/lib/dashboard/age` transitively
 *     through `lib/demo/demoData.ts`, and Node cannot resolve the alias.
 *
 * WHAT WAS TRIED FIRST AND DOES NOT WORK. `helpers/renderTsx.mjs` transpiles a
 * module and rewrites every import specifier in the OUTPUT before importing it
 * as a data: URL; adding the JSON attribute to that rewrite is the obvious
 * extension and it is not enough. It rewrites the ENTRY module only, by design,
 * so `sampleInbox.ts` loads and then `demoData.ts` — reached as an ordinary
 * file URL — dies on its own `@/lib/dashboard/age`. Making it work means
 * rewriting the whole local graph, which is a small bundler sitting next to the
 * real one.
 *
 * WHAT THIS DOES INSTEAD. Registers loader hooks, so the rewrites apply to
 * every module in the graph rather than to one file, and Node keeps doing the
 * type-stripping itself. No transpiler, and nothing to keep in step with
 * tsconfig beyond the alias.
 *
 * WHAT IT IS NOT. Still not a Next.js environment: this loads library modules,
 * not components. A module reaching for `next/*` or a browser global will fail
 * here and belongs to `renderTsx.mjs` or to Playwright.
 */
import { register } from "node:module";
import { resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

register("./appModuleHooks.mjs", import.meta.url);

/** `apps/web`, from `tests/unit/helpers/`. */
const WEB_ROOT = resolvePath(fileURLToPath(import.meta.url), "../../../..");

/** Import an app module by path relative to `apps/web`. */
export function importApp(relativePath) {
  return import(pathToFileURL(resolvePath(WEB_ROOT, relativePath)).href);
}
