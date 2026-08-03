/**
 * Server-side data assembly for the sidebar rail.
 *
 * The redesigned sidebar is not just navigation — it carries a glanceable
 * pipeline snapshot (total + stage distribution + the needs-review nudge) and
 * the Gmail connection state. This module gathers that signal ONCE per server
 * render of the shell, through the same helpers the dashboard already uses:
 *
 *   - `GET /applications/summary` via the typed client — counts only, O(1)
 *     transfer, folded through `summarizeCounts` so the rail can never show a
 *     number derived differently from the dashboard's tiles.
 *   - `getGmailStatus()` — connected + account email, with its labelled
 *     failure modes collapsed to "unknown" here (the rail is a glance, not a
 *     diagnostic surface; Settings owns the detailed story).
 *
 * Both fetches run in parallel and every failure degrades to `null` rather
 * than throwing, so a broken backend can never take the app shell down with
 * it — the rail simply renders its honest fallback. No client polling: the
 * snapshot re-fetches on server render / `router.refresh()` (which the
 * re-sync affordances already trigger).
 *
 * The exported types are plain serializable objects so the client `Sidebar`
 * can receive them as props; client modules must import them with
 * `import type` (erased at compile time — this module itself is server-only
 * via `lib/api/server`).
 */
import { createServerApiClient } from "@/lib/api/server";
import { summarizeCounts, type PipelineSummary } from "@/lib/dashboard/summary";
import { getGmailStatus } from "@/lib/gmail/server";

export interface RailPipelineData {
  /** Same fold as the dashboard tiles/funnel — one implementation of truth. */
  summary: PipelineSummary;
  /** Uncertain verdicts held for the user — the rail's amber nudge. */
  needsReview: number;
}

export interface RailGmailData {
  connected: boolean;
  email: string | null;
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
    const res = await api.GET("/applications/summary");
    if (res.error || !res.data) return null;
    return {
      summary: summarizeCounts(res.data.status_counts, res.data.total, res.data.this_week),
      needsReview: res.data.needs_review ?? 0,
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
  };
}

/** Fetch everything the rail shows, in parallel, never throwing. */
export async function loadRailData(): Promise<RailData> {
  const [pipeline, gmail] = await Promise.all([loadPipeline(), loadGmail()]);
  return { pipeline, gmail };
}
