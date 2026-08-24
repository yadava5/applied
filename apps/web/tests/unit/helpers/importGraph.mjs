/**
 * A transitive STATIC import walk over `apps/web`, used to ask reachability
 * questions about the bundle a route ships.
 *
 * It takes the web root as an argument rather than deriving it, so the same
 * code can be pointed at a different checkout — that is what makes a control
 * run ("does this gate go red on the commit that had the defect?") a control
 * and not a re-implementation of the thing under test.
 *
 * WHAT IT FOLLOWS
 *
 *   import x from "…"      import { x } from "…"      import "…"
 *   import type { x } from "…"                        export … from "…"
 *
 * Relative and `@/`-rooted specifiers only. A bare specifier (`react`,
 * `next/link`, `lucide-react`) resolves into `node_modules` and is not part of
 * the question being asked, so it terminates the walk.
 *
 * WHAT IT DELIBERATELY DOES NOT FOLLOW, AND WHY THAT IS THE LOOPHOLE
 *
 * `await import("…")`. Both patterns are anchored at the start of a line, so an
 * `import(...)` sitting inside an expression cannot match. That is intentional
 * and it is the entire point of the lazy boundaries in `lib/gmail/transport.ts`
 * and `lib/settings/transport.ts`: behind an `await import()` the fixtures are
 * their own chunk and do not ride the route's bundle. Both were measured in a
 * production build (#495), not assumed.
 *
 * So yes — this walk can be defeated by writing `await import("@/lib/demo/…")`
 * in a signed-in component. That is a deliberate escape hatch, not an oversight,
 * and anyone taking it is claiming the module is lazily loaded. Verify that
 * claim the way #495 did: build, and grep the route's chunk for a string that
 * exists only in the fixture data.
 *
 * TYPE-ONLY IMPORTS ARE FOLLOWED TOO. They are erased at build time and ship
 * nothing, so this is stricter than the bundle requires — on purpose. An
 * `import type` out of a fixture module is still the product borrowing the
 * demo's vocabulary, and the type belongs somewhere shared. If this ever fires
 * on a type-only edge, MOVE THE TYPE; do not loosen the walk.
 */
import { readFileSync, existsSync, statSync, readdirSync } from "node:fs";
import { join, dirname, resolve, relative } from "node:path";

/** `import`/`export … from "spec"`, and bare `import "spec"`. Anchored at the
 *  start of a line so `await import(…)` and any mention inside a comment or a
 *  string cannot match. */
const STATIC_IMPORT =
  /(?:^|\n)\s*(?:import|export)\s+(?:[^"';]*?\sfrom\s+)?["']([^"']+)["']|(?:^|\n)\s*import\s+["']([^"']+)["']/g;

const EXTENSIONS = ["", ".ts", ".tsx", ".mjs", ".js"];

function probe(base) {
  for (const ext of EXTENSIONS) {
    const candidate = base + ext;
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  for (const index of ["index.ts", "index.tsx"]) {
    const candidate = join(base, index);
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function resolveSpecifier(spec, fromFile, webRoot) {
  if (spec.startsWith("@/")) return probe(join(webRoot, spec.slice(2)));
  if (spec.startsWith(".")) return probe(resolve(dirname(fromFile), spec));
  return null;
}

/** Every `page.tsx` / `layout.tsx` under `dir`, absolute. Throws when the
 *  directory is missing — a gate whose inputs vanished must not report zero. */
export function routeEntrypoints(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...routeEntrypoints(path));
    else if (entry.name === "page.tsx" || entry.name === "layout.tsx") out.push(path);
  }
  return out;
}

/**
 * Walk every static import reachable from `entrypoints`.
 *
 * @returns {{ closure: Map<string,string|null>, chainTo: (file: string) => string[] }}
 *   `closure` maps each reached file to the file that first reached it (null
 *   for an entrypoint); `chainTo` renders that back into a readable path, so a
 *   failure can name HOW something was reached rather than only that it was.
 */
export function importClosure(webRoot, entrypoints) {
  const closure = new Map();
  const queue = entrypoints.map((file) => [file, null]);
  while (queue.length > 0) {
    const [file, parent] = queue.shift();
    if (closure.has(file)) continue;
    closure.set(file, parent);
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(STATIC_IMPORT)) {
      const resolved = resolveSpecifier(match[1] ?? match[2], file, webRoot);
      if (resolved !== null && !closure.has(resolved)) queue.push([resolved, file]);
    }
  }
  const chainTo = (file) => {
    const chain = [];
    for (let cursor = file; cursor != null; cursor = closure.get(cursor)) {
      chain.push(relative(webRoot, cursor));
    }
    return chain.reverse();
  };
  return { closure, chainTo };
}

/** Every module under `lib/demo/` the closure reaches, as repo-relative paths
 *  with the import chain that got there. */
export function demoModulesReached(webRoot, entrypoints) {
  const { closure, chainTo } = importClosure(webRoot, entrypoints);
  const hits = [];
  for (const file of closure.keys()) {
    const rel = relative(webRoot, file).split("\\").join("/");
    if (rel.startsWith("lib/demo/")) hits.push({ module: rel, chain: chainTo(file) });
  }
  hits.sort((a, b) => a.module.localeCompare(b.module));
  return { hits, closure, chainTo };
}
