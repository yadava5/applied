/**
 * Server-only helpers for the Gmail connection surface.
 *
 * These talk to the FastAPI backend's cloud Gmail endpoints (issue C5)
 * carrying the caller's Supabase JWT — the token and `BACKEND_API_URL`
 * never reach the browser. Every call degrades to a *labelled* state
 * instead of throwing, so the settings / inbox pages can render an honest
 * view rather than a crash.
 *
 * The labels are deliberately fine-grained. A failed authed call has three
 * very different causes and the user's next step differs for each:
 *
 *   - `unauthenticated` — no Supabase session on this request → sign in.
 *   - `auth`            — the backend rejected the JWT (401/403). The most
 *                         common live cause is the backend missing
 *                         `JOBTRACKER_SUPABASE_JWKS_URL` for an ES256 project,
 *                         or an expired session → sign in again / operator fix.
 *   - `unavailable`     — the backend reports Gmail isn't configured on this
 *                         deploy (503) → honest "not enabled yet".
 *   - `backend`         — any other non-2xx / network error → transient, retry.
 *
 * Collapsing all of these into one "unavailable" message (the previous
 * behaviour) told a signed-in tester "Gmail isn't enabled on this deployment
 * yet" even when the real cause was an auth rejection — a dead end. Keeping
 * them distinct is what lets the connect + inbox surfaces stay honest.
 *
 * We use plain `fetch` (not the typed `openapi-fetch` client) so the C5
 * endpoints don't need to be baked into the committed seed OpenAPI schema
 * — they resolve at runtime against the deployed backend.
 */
import { serverEnv } from "@/lib/env";
import type { InboxPage, PipelineAnalysis } from "@/lib/gmail/types";
import { getAccessToken } from "@/lib/supabase/auth";

/**
 * `GET /auth/gmail/status` — availability, linkage, and the caller's sync
 * cursor state. Mirrors the backend `GmailStatusResponse` field-for-field
 * (`cloud/gmail_oauth.py`); the last four are what the web renders as
 * "last synced …" so the product stops feeling like it never synced.
 */
export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  email: string | null;
  /**
   * ISO-8601 of the last *successful* sync, WITH an explicit UTC offset (the
   * backend's `_iso_utc`, so `new Date()` cannot read it as local time), or
   * `null` until one succeeds. An instant — parse it through
   * `lib/gmail/sync-state`, never through the calendar-date helper.
   */
  last_sync_at: string | null;
  /** A Gmail `historyId` is stored, so the next server-side sync is incremental. */
  has_cursor: boolean;
  /** Last recorded state. The cloud path only ever writes `idle` or `error`. */
  sync_status: string | null;
  /** On error, the failure's type name (a reference code, not a message). */
  sync_error: string | null;
}

/** Why an authenticated backend call did not succeed. */
export type GmailFailure =
  /** No Supabase session on this request — the user is signed out. */
  | { kind: "unauthenticated" }
  /** Backend rejected the JWT (401/403) — expired session or JWKS/secret misconfig. */
  | { kind: "auth"; status: number }
  /** Backend says Gmail isn't configured on this deployment (503). */
  | { kind: "unavailable" }
  /** Any other non-2xx or a network error — treat as transient. */
  | { kind: "backend"; message: string; status?: number };

export type GmailStatusResult = { kind: "ok"; status: GmailStatus } | GmailFailure;

/** One fetched page of the classified inbox, or a labelled failure. */
export type GmailInboxPageResult =
  | { kind: "ok"; page: InboxPage }
  | { kind: "not_connected" }
  | GmailFailure;

/** The whole-set pipeline analysis (summary + follow-ups), or a failure. */
export type GmailPipelineResult =
  | { kind: "ok"; analysis: PipelineAnalysis }
  | GmailFailure;

/** Result of persisting the pipeline into Application rows. */
export interface GmailSyncOutcome {
  created: number;
  updated: number;
  applications: number;
  scanned: number;
}

export type GmailSyncResult =
  | { kind: "ok"; result: GmailSyncOutcome }
  | { kind: "not_connected" }
  | GmailFailure;

export type GmailAuthorizeResult = { kind: "ok"; url: string } | GmailFailure;

async function sessionToken(): Promise<string | null> {
  // Request-memoized (lib/supabase/auth) so the Settings page's user read and
  // this Gmail-status read share one session decode rather than two.
  return getAccessToken();
}

/**
 * Map a non-2xx backend response to a labelled failure. 401/403 are auth
 * problems (the JWT was rejected); 503 is the honest "not configured on this
 * deploy" signal the routers emit; everything else is a transient backend
 * error the user can retry.
 */
function classifyBadResponse(status: number): GmailFailure {
  if (status === 401 || status === 403) return { kind: "auth", status };
  if (status === 503) return { kind: "unavailable" };
  return { kind: "backend", message: `Backend responded ${status}`, status };
}

function networkFailure(err: unknown): GmailFailure {
  return {
    kind: "backend",
    message: err instanceof Error ? err.message : "Backend unreachable",
  };
}

/** GET /auth/gmail/status — is Gmail available on this deploy, and linked? */
export async function getGmailStatus(): Promise<GmailStatusResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/auth/gmail/status`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return classifyBadResponse(res.status);
    return { kind: "ok", status: (await res.json()) as GmailStatus };
  } catch (err) {
    return networkFailure(err);
  }
}

/**
 * GET /auth/gmail/authorize — resolve the Google consent URL for the current
 * user. Returns a labelled failure (never throws) so the authorize route
 * handler can bounce the browser to the *right* place: `/login` for a missing
 * session, or `/settings?gmail=<flag>` with an honest flag otherwise.
 */
export async function getGmailAuthorizeUrl(): Promise<GmailAuthorizeResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/auth/gmail/authorize`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return classifyBadResponse(res.status);
    const data = (await res.json()) as { authorization_url?: string };
    if (!data.authorization_url) {
      return { kind: "backend", message: "Backend returned no authorization URL" };
    }
    return { kind: "ok", url: data.authorization_url };
  } catch (err) {
    return networkFailure(err);
  }
}

/** POST /auth/gmail/disconnect — revoke at Google + delete the stored token. */
export async function disconnectGmail(): Promise<boolean> {
  try {
    const token = await sessionToken();
    if (!token) return false;

    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/auth/gmail/disconnect`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * GET /gmail/inbox — fetch ONE server-side page of classified mail.
 *
 * `search` is the already-built query string (count / range / scope /
 * page_size / page_token). The web client loops this helper via the
 * `/api/gmail/inbox` proxy, accumulating pages until it reaches the user's
 * chosen count or `next_page_token` is null. The JWT and `BACKEND_API_URL`
 * never leave the server.
 */
export async function fetchGmailInboxPage(search: string): Promise<GmailInboxPageResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const suffix = search ? `?${search}` : "";
    const res = await fetch(`${BACKEND_API_URL}/gmail/inbox${suffix}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (res.status === 409) return { kind: "not_connected" };
    if (!res.ok) return classifyBadResponse(res.status);
    return { kind: "ok", page: (await res.json()) as InboxPage };
  } catch (err) {
    return networkFailure(err);
  }
}

/**
 * POST /gmail/pipeline — analyze the accumulated verdict set for the canonical
 * category summary + "no response / follow-up" flags across ALL fetched pages.
 * Pure aggregation on the backend over data the client already holds; no Gmail
 * call. `items` is passed straight through (the backend bounds its size).
 */
export async function analyzeGmailPipeline(items: unknown): Promise<GmailPipelineResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/gmail/pipeline`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ items }),
      cache: "no-store",
    });
    if (!res.ok) return classifyBadResponse(res.status);
    return { kind: "ok", analysis: (await res.json()) as PipelineAnalysis };
  } catch (err) {
    return networkFailure(err);
  }
}

/**
 * POST /gmail/sync — persist the classified pipeline into Application rows so
 * the dashboard shows REAL data. `body` is either `{ items }` (the mined set
 * relayed from the inbox workbench) or `{}` / range knobs (the backend fetches
 * a bounded recent page itself). Idempotent upsert on the backend; the JWT and
 * BACKEND_API_URL never leave the server.
 */
export async function syncGmailPipeline(body: unknown): Promise<GmailSyncResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/gmail/sync`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body ?? {}),
      cache: "no-store",
    });
    if (res.status === 409) return { kind: "not_connected" };
    if (!res.ok) return classifyBadResponse(res.status);
    return { kind: "ok", result: (await res.json()) as GmailSyncOutcome };
  } catch (err) {
    return networkFailure(err);
  }
}
