/**
 * Server-side data assembly for the sidebar rail.
 *
 * The redesigned sidebar is not just navigation — it is the app's instrument
 * column: a glanceable pipeline snapshot (total + stage distribution), the
 * pulse's four derived signals (momentum, ageing, deadlines, classifier), and
 * the Gmail connection state. This module gathers that signal ONCE per server
 * render of the shell, through the same helpers the dashboard already uses:
 *
 *   - `GET /applications/summary` via the typed client — counts only, O(1)
 *     transfer, folded through `summarizeCounts` so the rail can never show a
 *     number derived differently from the dashboard's tiles.
 *   - `GET /applications` (page 1, `BOARD_PAGE_SIZE`) — the board's own
 *     bounded page, projected down to `PulseRow` so the rail's signals derive
 *     from the same rows the board renders without shipping them twice.
 *   - `getGmailStatus()` — connected + account email + the sync cursor state
 *     ("last synced …"), with its labelled failure modes collapsed to
 *     "unknown" here (the rail is a glance, not a diagnostic surface; Settings
 *     owns the detailed story).
 *
 * Both fetches run in parallel and every failure degrades to `null` rather
 * than throwing, so a broken backend can never take the app shell down with
 * it — the rail simply renders its honest fallback. No client polling: the
 * snapshot re-fetches on server render / `router.refresh()` (which the
 * dashboard's sync affordances already trigger).
 *
 * The exported types are plain serializable objects so the client `Sidebar`
 * can receive them as props; client modules must import them with
 * `import type` (erased at compile time — this module itself is server-only
 * via `lib/api/server`).
 */
import { createServerApiClient } from "@/lib/api/server";
import { BOARD_PAGE_SIZE } from "@/lib/dashboard/boardPage";
import {
  summarizeCounts,
  toPulseRow,
  type PipelineSummary,
  type PulseRow,
} from "@/lib/dashboard/summary";
import { getGmailStatus } from "@/lib/gmail/server";

export interface RailPipelineData {
  /** Same fold as the dashboard tiles/funnel — one implementation of truth. */
  summary: PipelineSummary;
  /** Uncertain verdicts held for the user — the classifier signal's amber link. */
  needsReview: number;
  /**
   * One bounded page of rows, projected to the fields the pulse's derived
   * signals read (momentum, ageing, deadlines, classifier share). The SAME
   * page the dashboard's board loads — identical URL, so React's request
   * memoization collapses the two fetches into one backend read when the
   * shell wraps /dashboard, and the rail describes exactly the slice the
   * board shows. `null` = the list fetch failed while the summary survived;
   * the rail then renders the counts it has and no derived signals, never a
   * guess.
   */
  pulseRows: PulseRow[] | null;
}

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
  /** `null` = backend unreachable / rejected — rail shows an honest fallback. */
  pipeline: RailPipelineData | null;
  /** `null` = status unknown (failure) — rail omits the connection chip. */
  gmail: RailGmailData | null;
}

async function loadPipeline(): Promise<RailPipelineData | null> {
  try {
    const api = await createServerApiClient();
    const [summaryRes, listRes] = await Promise.all([
      api.GET("/applications/summary"),
      api.GET("/applications", {
        params: { query: { page: 1, page_size: BOARD_PAGE_SIZE } },
      }),
    ]);
    if (summaryRes.error || !summaryRes.data) return null;
    return {
      summary: summarizeCounts(
        summaryRes.data.status_counts,
        summaryRes.data.total,
        summaryRes.data.this_week,
      ),
      needsReview: summaryRes.data.needs_review ?? 0,
      pulseRows:
        listRes.error || !listRes.data ? null : listRes.data.applications.map(toPulseRow),
    };
  } catch {
    return null;
  }
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

/** Fetch everything the rail shows, in parallel, never throwing. */
export async function loadRailData(): Promise<RailData> {
  const [pipeline, gmail] = await Promise.all([loadPipeline(), loadGmail()]);
  return { pipeline, gmail };
}
