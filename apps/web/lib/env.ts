/**
 * Runtime-validated environment variables for the web app.
 *
 * Centralising access through a zod schema means missing or malformed values
 * fail fast at module import time with a clear message, rather than leaking
 * `undefined` into Supabase clients, fetchers, or middleware where the
 * resulting errors are opaque.
 *
 * IMPORTANT: this file is imported from both server (`lib/supabase/server`,
 * `proxy.ts`) and client bundles (`lib/supabase/client`). It MUST only
 * reference `NEXT_PUBLIC_*` keys in the browser path; the server-only keys
 * below are read via a lazy getter so that Next.js's tree-shaking keeps
 * them out of the client bundle.
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
 * Keeping the two messages apart is the entire point of this file: "is
 * required" tells you to add the variable to `.env.local` or the Vercel
 * project, while "must be a valid URL" tells you the value you already set is
 * wrong. Collapsing them into one string would still fail the build, but
 * would fail it uninformatively.
 */
const missingOrInvalid =
  (missing: string, invalid: string) =>
  (issue: { input: unknown }): string =>
    issue.input === undefined ? missing : invalid;

const publicSchema = z.object({
  // `z.url()` rather than the now-deprecated `z.string().url()`: zod 4 models
  // string formats as ZodString subclasses on the top-level namespace.
  NEXT_PUBLIC_SUPABASE_URL: z.url({
    error: missingOrInvalid(
      "NEXT_PUBLIC_SUPABASE_URL is required",
      "NEXT_PUBLIC_SUPABASE_URL must be a valid URL",
    ),
  }),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z
    .string({
      error: missingOrInvalid(
        "NEXT_PUBLIC_SUPABASE_ANON_KEY is required",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY must be a string",
      ),
    })
    // A check-level message still outranks the schema-level `error` above, so
    // an empty-but-present key keeps its own wording.
    .min(1, "NEXT_PUBLIC_SUPABASE_ANON_KEY must not be empty"),
});

const serverSchema = z.object({
  BACKEND_API_URL: z.url({
    error: missingOrInvalid(
      "BACKEND_API_URL is required",
      "BACKEND_API_URL must be a valid URL",
    ),
  }),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1).optional(),
});

type PublicEnv = z.infer<typeof publicSchema>;
type ServerEnv = z.infer<typeof serverSchema>;

// zod 4 removed `ZodError.errors`; `.issues` was always the real property and
// is now the only one.
function formatZodError(err: z.ZodError): string {
  return err.issues
    .map((issue) => `  - ${issue.path.join(".")}: ${issue.message}`)
    .join("\n");
}

/**
 * Client-safe env — keys prefixed with `NEXT_PUBLIC_` only. Safe to import
 * from React Client Components.
 */
export const publicEnv: PublicEnv = (() => {
  const result = publicSchema.safeParse({
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  });
  if (!result.success) {
    throw new Error(
      `[env] invalid public environment variables:\n${formatZodError(result.error)}`,
    );
  }
  return result.data;
})();

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
