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
 *
 * `snippet` is NOT optional either, and for a sharper version of the same
 * reason (#484). This relay used to forward seven fields and drop it, even
 * though the mine hands us one on every verdict — so `PipelineItemIn.snippet`
 * took its `""` default, `_persist_message_refs` wrote an empty
 * `body_snippet`, and every reader that falls back to the stored text read
 * ZERO characters instead of Gmail's ~200. Measured on a row this path wrote:
 *
 *     PipelineItemIn.snippet = '' len 0
 *     stored body_snippet    = ''
 *     identity_parts(...)    -> (None, None)      # nothing-grade
 *     identity_parts(same subject, the real 180-char snippet)
 *                            -> ('Backend Platform Engineer', None)
 *
 * That is worse than the "snippet-grade" fallback the server-side comments
 * describe: the relay path is documented as sending the reader BACK to the
 * snippet, and there was no snippet to go back to. Forwarding it restores the
 * behaviour those comments already claim.
 *
 * IT IS NOT `string | null`. `InboxVerdict.snippet` is `string | null |
 * undefined` (null is the real value for a message with no preview, and a
 * rehydrated older snapshot has no key at all), while `PipelineItemIn.snippet`
 * is a plain `str` with no `None` in its annotation. `undefined` is harmless —
 * `JSON.stringify` drops the key and the default applies — but a literal
 * `null` on the wire is a 422, and `SyncRequest.items` is a homogeneous list,
 * so ONE preview-less message would reject the whole batch and file nothing.
 * Verified against the shipped schema: `PipelineItemIn(snippet=None)` raises
 * `Input should be a valid string`. Hence the `?? ""` below, and hence this
 * field being required here so `tsc` names any other producer.
 *
 * THERE IS DELIBERATELY NO `identity_role`/`identity_req_id`. `PipelineItemIn`
 * refuses them on purpose — they decide which application a message is filed
 * against, and a client that could state them could reshape dedup keys and
 * file its own mail onto whichever application it named. The server ignores
 * them if sent; this relay does not send them.
 */
export interface PipelineItem {
  message_id: string;
  category: string;
  sender_email: string;
  subject: string;
  sender_name: string | null;
  received_at: string | null;
  confidence: number;
  snippet: string;
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
    // Coalesced, never relayed as null — see the interface comment. A message
    // with no preview sends `""`, which is what the endpoint's own default
    // already was, so nothing about that case changes.
    snippet: v.snippet ?? "",
  }));
}

/** One page of the mine. `page` is null for any non-OK status. */
export interface ScanPageResult {
  status: number;
  page: InboxPage | null;
  /**
   * Seconds to wait before re-requesting the SAME page, when the backend
   * deferred this read (429). Absent on every other outcome.
   */
  retryAfterSeconds?: number;
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
    if (res.status === 429) {
      // The proxy passes Gmail's deferral through with the wait intact. The
      // fallback matches the quota bucket's own period; see
      // `RETRY_AFTER_FALLBACK_SECONDS` in `lib/gmail/server.ts`.
      const raw = Number(res.headers.get("Retry-After"));
      return {
        status: 429,
        page: null,
        retryAfterSeconds: Number.isFinite(raw) && raw > 0 ? Math.ceil(raw) : 60,
      };
    }
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

/**
 * The fixtures are loaded with a DYNAMIC import, and that is not decoration.
 *
 * `ReclassifyControl` and `InboxWorkbench` both pull this module, and both
 * render on the signed-in `/inbox`. A top-level `import` of the fixture mail
 * therefore shipped six invented emails into the bundle of every reader who has
 * never opened `/demo/scan` — measured in the production build: the chunk
 * carrying `InboxWorkbench` also carried "Your HackerRank assessment…". Behind
 * an `await import()` the fixtures are their own chunk, fetched only when the
 * demo transport actually runs.
 */
const demo: ScanTransport = {
  mode: "demo",
  async fetchPage() {
    // Long enough that the progress bar renders and can be asserted; no
    // network, no Gmail, no classifier — the verdicts are fixtures.
    await delay(120);
    const { demoScanMine } = await import("@/lib/demo/scanMine");
    // Dated per mine rather than at module load: a frozen resolution shows
    // whatever day the server booted on.
    const verdicts = demoScanMine();
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
    const { demoClassifyOutcome } = await import("@/lib/demo/scanMine");
    return { ok: true, body: demoClassifyOutcome(messageId, body) };
  },
};

export function scanTransport(mode: ScanMode): ScanTransport {
  return mode === "demo" ? demo : live;
}
