/**
 * The live-scan workbench's transport seam — how the mine, the whole-set
 * analysis, the file action and a per-row correction reach the world.
 *
 * Same pattern as `lib/settings/transport.ts`, and for the same reason: the
 * scan view is auth-gated AND Gmail-gated, so CI (which has neither a Supabase
 * session nor a connected mailbox) could never render it, and no test could
 * reach a single control on it. The workbench now takes a serializable `mode`
 * string, which a Server Component can choose, and resolves its transport
 * here. `live` makes exactly the requests the component used to make inline —
 * same URLs, same headers, same abort signal, same "a non-OK status is data,
 * a network failure throws" contract, so the signed-in path is unchanged.
 * `demo` runs the identical component over a fixture mine and simulated
 * outcomes: nothing it does touches the network.
 *
 * The demo transport deliberately reproduces the ONE response shape that makes
 * this feature hard — `needs_employer: true`, a 2xx that filed nothing — so
 * the e2e exercises the branch that matters instead of only the happy path.
 */
import { DEMO_SCAN_MINE, demoClassifyOutcome } from "@/lib/demo/scanMine";
import type { ClassifyRequestBody } from "@/lib/dashboard/review";
import type { InboxPage, InboxVerdict, PipelineAnalysis } from "@/lib/gmail/types";
import type { SyncCounts } from "@/lib/gmail/sync-state";

export type ScanMode = "live" | "demo";

/**
 * The minimal shape `/gmail/pipeline` and `/gmail/sync` need for one message.
 *
 * `confidence` is NOT optional: the backend's `PipelineItemIn` defaults it to
 * 0.0 and `/gmail/sync` gates persistence on it (auto-file at 0.85, review
 * floor at 0.70). Omitting it meant every relayed item scored 0.0, fell below
 * both gates, and nothing was ever filed.
 */
export interface PipelineItem {
  message_id: string;
  category: string;
  sender_email: string;
  subject: string;
  sender_name: string | null;
  received_at: string | null;
  confidence: number;
}

/** Reduce mined verdicts to what the pipeline/sync endpoints consume. */
export function toPipelineItems(verdicts: InboxVerdict[]): PipelineItem[] {
  return verdicts.map((v) => ({
    message_id: v.message_id,
    category: v.category,
    sender_email: v.sender_email,
    subject: v.subject,
    sender_name: v.sender_name,
    received_at: v.received_at,
    confidence: v.confidence,
  }));
}

/** One page of the mine. `page` is null for any non-OK status. */
export interface ScanPageResult {
  status: number;
  page: InboxPage | null;
}

export interface ScanFileResult {
  ok: boolean;
  status: number;
  counts: Partial<SyncCounts>;
}

/** A classify response, unreshaped — `readClassifyOutcome` reads the branch. */
export interface ScanClassifyResult {
  ok: boolean;
  body: unknown;
}

export interface ScanTransport {
  mode: ScanMode;
  fetchPage(query: string, signal: AbortSignal): Promise<ScanPageResult>;
  analyze(items: PipelineItem[], signal: AbortSignal): Promise<PipelineAnalysis | null>;
  file(items: PipelineItem[]): Promise<ScanFileResult>;
  classify(messageId: string, body: ClassifyRequestBody): Promise<ScanClassifyResult>;
}

/** The classify half on its own — the only piece a filed row needs too. */
export type ClassifyFn = ScanTransport["classify"];

export const liveClassify: ClassifyFn = async (messageId, body) => {
  const res = await fetch(`/api/applications/review/${encodeURIComponent(messageId)}/classify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, body: await res.json().catch(() => ({})) };
};

const live: ScanTransport = {
  mode: "live",
  async fetchPage(query, signal) {
    const res = await fetch(`/api/gmail/inbox?${query}`, { cache: "no-store", signal });
    if (!res.ok) return { status: res.status, page: null };
    return { status: res.status, page: (await res.json()) as InboxPage };
  },
  async analyze(items, signal) {
    const res = await fetch("/api/gmail/pipeline", {
      method: "POST",
      cache: "no-store",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    // `null` means "it answered, but not with an analysis" — the caller shows
    // the follow-up panel as unavailable rather than as empty.
    if (!res.ok) return null;
    return (await res.json()) as PipelineAnalysis;
  },
  async file(items) {
    const res = await fetch("/api/gmail/sync", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, mode: "additive" }),
    });
    if (!res.ok) return { ok: false, status: res.status, counts: {} };
    return {
      ok: true,
      status: res.status,
      counts: (await res.json().catch(() => ({}))) as Partial<SyncCounts>,
    };
  },
  classify: liveClassify,
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const demo: ScanTransport = {
  mode: "demo",
  async fetchPage() {
    // Long enough that the progress bar renders and can be asserted; no
    // network, no Gmail, no classifier — the verdicts are fixtures.
    await delay(120);
    const verdicts = DEMO_SCAN_MINE;
    const summary: Record<string, number> = {};
    for (const v of verdicts) summary[v.category] = (summary[v.category] ?? 0) + 1;
    const page: InboxPage = {
      connected: true,
      scanned: verdicts.length,
      verdicts,
      next_page_token: null,
      category_summary: summary,
      query: "in:inbox newer_than:6m",
      scope: "inbox",
      range_months: 6,
      note: "fixture mine — no mailbox is read",
    };
    return { status: 200, page };
  },
  async analyze(items) {
    await delay(80);
    const summary: Record<string, number> = {};
    for (const i of items) summary[i.category] = (summary[i.category] ?? 0) + 1;
    return {
      total: items.length,
      job_related: items.filter((i) => i.category !== "other").length,
      category_summary: summary,
      follow_ups: [],
    };
  },
  async file(items) {
    await delay(200);
    // Says what it is: the demo files nothing, and reports that honestly
    // through the same counts the real sync returns.
    return {
      ok: true,
      status: 200,
      counts: { created: 0, updated: 0, applications: 0, scanned: items.length },
    };
  },
  async classify(messageId, body) {
    await delay(150);
    return { ok: true, body: demoClassifyOutcome(messageId, body) };
  },
};

export function scanTransport(mode: ScanMode): ScanTransport {
  return mode === "demo" ? demo : live;
}
