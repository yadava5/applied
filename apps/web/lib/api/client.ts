/**
 * Typed API client factory.
 *
 * Wraps `openapi-fetch` with the generated `paths` type so every `.GET` /
 * `.POST` call is narrowed against the backend's OpenAPI schema.
 *
 * WHERE `lib/api/schema.d.ts` COMES FROM
 * --------------------------------------
 * It is GENERATED — never hand-edited — from `jobtracker.main_cloud`, the app
 * Vercel actually serves:
 *
 *     pnpm -C apps/web api:gen        # → scripts/generate_api_schema.sh
 *
 * `.github/workflows/e2e-ci.yml` runs the same script and fails the build on
 * any diff, so the committed file cannot drift from the backend again.
 *
 * It used to be a 180-line file hand-written by us, covering 4 of the 20
 * endpoints the cloud app serves and describing response shapes nobody sent.
 * Everything outside those 4 paths was therefore unchecked — which is how
 * the detail sheet came to read `split_candidates[].position` when the
 * backend has only ever sent `role`, silently dropping every candidate and
 * making the split feature unreachable in the product (#100). A contract the
 * compiler cannot see is not a contract.
 * The factory is environment-agnostic — it does not touch cookies or
 * Supabase directly. Pass `token` explicitly from whichever context can
 * read it:
 *
 *   - Server Components / Route Handlers → `lib/api/server.ts` (uses the
 *     Supabase SSR client to read the access token from cookies).
 *   - Client Components → read `supabase.auth.getSession()` in the browser
 *     and pass `session.access_token` here.
 *
 * Keeping the factory pure also makes it trivially testable.
 */
import createClient, { type Client } from "openapi-fetch";

import type { paths } from "@/lib/api/schema";

export interface CreateApiClientOptions {
  /** FastAPI base URL, e.g. `https://api.jobtracker.app`. Required. */
  baseUrl: string;
  /**
   * Supabase-issued JWT. When present, every request is sent with
   * `Authorization: Bearer <token>`. Omit for unauthenticated probes
   * such as `/health`.
   */
  token?: string;
  /**
   * Extra default headers merged in after the `Authorization` header.
   * Useful for `X-Request-Id` tracing or custom `Accept` overrides.
   */
  headers?: Record<string, string>;
}

/** Convenience alias for callers that want to strongly type a returned client. */
export type ApiClient = Client<paths>;

/**
 * Build an `openapi-fetch` client bound to our generated `paths` type.
 */
export function createApiClient(options: CreateApiClientOptions): ApiClient {
  const { baseUrl, token, headers } = options;

  const mergedHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers ?? {}),
  };

  if (token) {
    mergedHeaders.Authorization = `Bearer ${token}`;
  }

  return createClient<paths>({
    baseUrl,
    headers: mergedHeaders,
  });
}
