/**
 * Client-safe environment variables — keys prefixed with `NEXT_PUBLIC_` only.
 *
 * Validating these still means missing or malformed values fail fast at module
 * import time with a clear message, rather than leaking `undefined` into
 * Supabase clients, fetchers, or the proxy where the resulting errors are
 * opaque. That guarantee is unchanged; what changed is the cost of it.
 *
 * WHY THIS FILE NO LONGER IMPORTS ZOD, and why the server half moved out
 * ---------------------------------------------------------------------
 * `lib/supabase/client.ts` is a `"use client"` module and imports `publicEnv`,
 * so every module in this file's import graph is compiled into the browser
 * bundle. The server schema lived here too, which meant the whole zod runtime
 * shipped to every visitor — measured on `origin/main` at 508.6 KB gzip across
 * the client chunks, of which zod was 63 KB, inside a single 126.9 KB chunk.
 * Nothing in a tab can use it: Next inlines `NEXT_PUBLIC_*` at build time, so
 * by the time this code runs in a browser the two values below are string
 * literals that were already checked when the build ran.
 *
 * A comment here used to claim tree-shaking kept the server keys out of the
 * client bundle. It did not, and could not: `serverSchema` was built by a
 * top-level `z.object(...)` call and reached from an exported function, so the
 * bundler had to keep it. The fix is a module boundary, not a hope about
 * elimination — `serverEnv()` and its zod schema now live in
 * `lib/env.server.ts`, which no client module imports.
 *
 * The checks here are hand-written rather than schema-driven because there are
 * two of them and the whole point (below) is the wording of two messages. A
 * validator library earns its keep on shapes this is not.
 */

/**
 * Keeping "missing" and "invalid" apart is the entire point of this file:
 * "is required" tells you to add the variable to `.env.local` or the Vercel
 * project, while "must be a valid URL" tells you the value you already set is
 * wrong. Collapsing them into one string would still fail the build, but
 * would fail it uninformatively.
 */
type Issue = { key: string; message: string };

/** `new URL()` rather than `URL.canParse()`: same answer, no baseline cliff. */
function isUrl(value: string): boolean {
  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

function requireUrl(key: string, value: string | undefined, issues: Issue[]): string {
  if (value === undefined) issues.push({ key, message: `${key} is required` });
  else if (!isUrl(value)) issues.push({ key, message: `${key} must be a valid URL` });
  return value ?? "";
}

function requireString(key: string, value: string | undefined, issues: Issue[]): string {
  if (value === undefined) issues.push({ key, message: `${key} is required` });
  // An empty-but-present key keeps its own wording — it is neither absent nor
  // malformed, and "must not be empty" is the sentence that says what to do.
  else if (value.length === 0) issues.push({ key, message: `${key} must not be empty` });
  return value ?? "";
}

export interface PublicEnv {
  NEXT_PUBLIC_SUPABASE_URL: string;
  NEXT_PUBLIC_SUPABASE_ANON_KEY: string;
}

/**
 * Client-safe env. Safe to import from React Client Components.
 *
 * Both keys are collected before throwing, not checked one at a time: a
 * `.env.local` missing both should say so once rather than over two failed
 * builds. `process.env.NEXT_PUBLIC_*` is also spelled out in full rather than
 * looked up dynamically — Next's inlining is a literal text substitution, so
 * an indexed read would compile to `undefined` in the browser.
 */
export const publicEnv: PublicEnv = (() => {
  const issues: Issue[] = [];
  const env: PublicEnv = {
    NEXT_PUBLIC_SUPABASE_URL: requireUrl(
      "NEXT_PUBLIC_SUPABASE_URL",
      process.env.NEXT_PUBLIC_SUPABASE_URL,
      issues,
    ),
    NEXT_PUBLIC_SUPABASE_ANON_KEY: requireString(
      "NEXT_PUBLIC_SUPABASE_ANON_KEY",
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      issues,
    ),
  };
  if (issues.length > 0) {
    const detail = issues.map((issue) => `  - ${issue.key}: ${issue.message}`).join("\n");
    throw new Error(`[env] invalid public environment variables:\n${detail}`);
  }
  return env;
})();
