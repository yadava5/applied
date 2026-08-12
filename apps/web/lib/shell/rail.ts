/**
 * Server-side data assembly for the sidebar rail.
 *
 * One probe: the Gmail connection state the rail footer renders beside the
 * signed-in identity — connected + account email + the sync cursor state
 * ("last synced …"), with its labelled failure modes collapsed to "unknown"
 * here (the rail is a glance, not a diagnostic surface; Settings owns the
 * detailed story).
 *
 * This module used to assemble a whole instrument column as well — the
 * pipeline summary, and one bounded page of rows for the pulse's derived
 * signals (PR #122). Both are gone from the rail: the pulse lives on the
 * dashboard's stage spine (`PipelineBoard`'s `pulse` prop) where the board's
 * own rows already are, and the snapshot's total restated a number the
 * dashboard screen already stated twice (see `components/shell/Sidebar` for
 * the measurements and the restatement note). With them went a summary read
 * and a full list read the shell was paying on every tab.
 *
 * The probe never throws — a failed status read degrades to `null` and the
 * rail omits the connection chip rather than guessing. The exported types are
 * plain serializable objects so the client `Sidebar` can receive them as
 * props; client modules must import them with `import type` (erased at
 * compile time — `lib/gmail/server` is server-only).
 */
import { getGmailStatus } from "@/lib/gmail/server";

export interface RailGmailData {
  connected: boolean;
  email: string | null;
  /** Instant of the last successful sync (explicit UTC offset), or `null`. */
  lastSyncAt: string | null;
  /** The next server-side sync can be incremental. Not claimed in the UI when false. */
  hasCursor: boolean;
  /** `idle` | `error` | `null` — the cloud path never writes `syncing`. */
  syncStatus: string | null;
  /** On `error`, the failure's type name — a reference code, not an explanation. */
  syncError: string | null;
}

export interface RailData {
  /** `null` = status unknown (failure) — rail omits the connection chip. */
  gmail: RailGmailData | null;
}

async function loadGmail(): Promise<RailGmailData | null> {
  const result = await getGmailStatus();
  if (result.kind !== "ok") return null;
  return {
    connected: result.status.configured && result.status.connected,
    email: result.status.email,
    // Sync state rides along on the SAME probe — the rail already made this
    // call, and "last synced 3 minutes ago" belongs beside "connected as …".
    lastSyncAt: result.status.last_sync_at ?? null,
    hasCursor: result.status.has_cursor === true,
    syncStatus: result.status.sync_status ?? null,
    syncError: result.status.sync_error ?? null,
  };
}

/** Fetch everything the rail shows, never throwing. */
export async function loadRailData(): Promise<RailData> {
  return { gmail: await loadGmail() };
}
