/**
 * Server-only helpers for the Gmail connection surface.
 *
 * These talk to the FastAPI backend's cloud Gmail endpoints (issue C5)
 * carrying the caller's Supabase JWT — the token and `BACKEND_API_URL`
 * never reach the browser. Every call degrades to a labelled state
 * instead of throwing, so the settings / inbox pages can render an honest
 * "not connected" / "not yet enabled" / "unreachable" view rather than a
 * crash while the operator finishes wiring the OAuth client.
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

export type GmailStatusResult =
  | { kind: "ok"; status: GmailStatus }
  | { kind: "unauthenticated" }
  | { kind: "unavailable"; message: string };

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
  | { kind: "unauthenticated" }
  | { kind: "unavailable"; message: string };

async function sessionToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

/** GET /auth/gmail/status — is Gmail available on this deploy, and linked? */
export async function getGmailStatus(): Promise<GmailStatusResult> {
  try {
    const token = await sessionToken();
    if (!token) return { kind: "unauthenticated" };

    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/auth/gmail/status`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return { kind: "unavailable", message: `Backend responded ${res.status}` };
    }
    return { kind: "ok", status: (await res.json()) as GmailStatus };
  } catch (err) {
    return {
      kind: "unavailable",
      message: err instanceof Error ? err.message : "Backend unreachable",
    };
  }
}

/**
 * GET /auth/gmail/authorize — resolve the Google consent URL for the
 * current user. Returns `null` when unauthenticated / unavailable so the
 * caller (the authorize route handler) can redirect back with a flag
 * instead of exposing an error page.
 */
export async function getGmailAuthorizeUrl(): Promise<string | null> {
  try {
    const token = await sessionToken();
    if (!token) return null;

    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/auth/gmail/authorize`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { authorization_url?: string };
    return data.authorization_url ?? null;
  } catch {
    return null;
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
  try {
    const token = await sessionToken();
    if (!token) return { kind: "unauthenticated" };

    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}/gmail/inbox`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (res.status === 409) return { kind: "not_connected" };
    if (!res.ok) {
      return { kind: "unavailable", message: `Backend responded ${res.status}` };
    }
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
    return {
      kind: "unavailable",
      message: err instanceof Error ? err.message : "Backend unreachable",
    };
  }
}
