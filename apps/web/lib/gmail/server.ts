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
import { createClient } from "@/lib/supabase/server";

export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  email: string | null;
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

export interface InboxVerdict {
  message_id: string;
  subject: string;
  sender_email: string;
  sender_name: string | null;
  category: string;
  confidence: number;
  method: string;
  needs_review: boolean;
}

export type GmailInboxResult =
  | { kind: "ok"; scanned: number; verdicts: InboxVerdict[]; note: string }
  | { kind: "not_connected" }
  | GmailFailure;

export type GmailAuthorizeResult = { kind: "ok"; url: string } | GmailFailure;

async function sessionToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
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

/** GET /gmail/inbox — read a bounded batch of recent mail and classify it. */
export async function getGmailInbox(): Promise<GmailInboxResult> {
  const token = await sessionToken();
  if (!token) return { kind: "unauthenticated" };

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/gmail/inbox`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (res.status === 409) return { kind: "not_connected" };
    if (!res.ok) return classifyBadResponse(res.status);
    const data = (await res.json()) as {
      scanned: number;
      verdicts: InboxVerdict[];
      note: string;
    };
    return {
      kind: "ok",
      scanned: data.scanned,
      verdicts: data.verdicts,
      note: data.note,
    };
  } catch (err) {
    return networkFailure(err);
  }
}
