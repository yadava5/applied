/**
 * Server-only environment variables, validated by zod.
 *
 * This is the half of the old `lib/env.ts` that must never reach a browser.
 * It lives in its own module for exactly that reason: `lib/env.ts` is imported
 * (transitively) by `"use client"` code, so anything in its graph is compiled
 * into the client bundle, and the zod runtime it needed was 63 KB gzip of dead
 * weight in every visitor's first load. Import this file only from Server
 * Components, Route Handlers, or the proxy runtime — never from a module that
 * a client component can reach.
 *
 * zod is kept HERE rather than hand-rolled the way the public half is: these
 * keys are read on paths that can fail long after deploy (a rotated backend
 * URL, a service-role key set to the wrong thing), the schema is where that
 * shape is stated once, and nothing about a server bundle is charged to a
 * visitor.
 */
import { z } from "zod";

/**
 * zod 4 removed `required_error`/`invalid_type_error` in favour of a single
 * `error` callback, so the "you forgot to set this" case is no longer a
 * separate option — the schema has to discriminate for itself. A key that is
 * absent from `process.env` reaches the callback as an `invalid_type` issue
 * whose `input` is `undefined`; anything else is a value that was set but is
 * the wrong shape.
 *
 * Keeping the two messages apart is the point: "is required" tells you to add
 * the variable to `.env.local` or the Vercel project, while "must be a valid
 * URL" tells you the value you already set is wrong.
 */
const missingOrInvalid =
  (missing: string, invalid: string) =>
  (issue: { input: unknown }): string =>
    issue.input === undefined ? missing : invalid;

const serverSchema = z.object({
  // `z.url()` rather than the now-deprecated `z.string().url()`: zod 4 models
  // string formats as ZodString subclasses on the top-level namespace.
  BACKEND_API_URL: z.url({
    error: missingOrInvalid(
      "BACKEND_API_URL is required",
      "BACKEND_API_URL must be a valid URL",
    ),
  }),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1).optional(),
});

type ServerEnv = z.infer<typeof serverSchema>;

// zod 4 removed `ZodError.errors`; `.issues` was always the real property and
// is now the only one.
function formatZodError(err: z.ZodError): string {
  return err.issues
    .map((issue) => `  - ${issue.path.join(".")}: ${issue.message}`)
    .join("\n");
}

/**
 * Server-only env. Access via `serverEnv()` so the validation only runs when
 * this module is loaded from a Server Component, Route Handler, or the
 * proxy runtime. Lazy evaluation means static-asset requests that never hit
 * server code will not crash if, say, `BACKEND_API_URL` is missing during
 * a local preview of client-side errors.
 */
let cachedServerEnv: ServerEnv | null = null;
export function serverEnv(): ServerEnv {
  if (cachedServerEnv) return cachedServerEnv;
  const result = serverSchema.safeParse({
    BACKEND_API_URL: process.env.BACKEND_API_URL,
    SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
  });
  if (!result.success) {
    throw new Error(
      `[env] invalid server environment variables:\n${formatZodError(result.error)}`,
    );
  }
  cachedServerEnv = result.data;
  return cachedServerEnv;
}
