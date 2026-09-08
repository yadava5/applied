/**
 * The board's transport seam — how the interactive components reach data.
 *
 * Every mutating surface (`ApplicationRow`, `ApplicationDetail`,
 * `PipelineBoard`'s drag, `SyncBar`) takes one of these interfaces and
 * defaults to the live implementation below, which talks to the same-origin
 * proxy routes exactly as before. The public `/demo` passes an in-memory
 * implementation instead (`components/demo/DemoDashboard.tsx`), so the demo
 * runs the REAL components' real state machines over fixture state — the
 * "demo is the real thing" contract — and the e2e suite can execute paths
 * (sync states, the rebuild receipt, the detail sheet, drag) that are
 * otherwise locked behind a Supabase session CI never has.
 *
 * Client-safe by construction: plain `fetch` against relative proxy paths,
 * no server-only imports. The request SHAPES still come from
 * `lib/dashboard/rowActions.ts`, so the which-endpoint-does-what guarantees
 * asserted in `tests/unit/row-actions.test.mjs` keep holding here.
 */
import {
  cacheDetail,
  clearDetailCache,
  invalidateDetail,
  readCachedDetail,
} from "@/lib/dashboard/detailCache";
import { LAST_LOOK_KEY } from "@/lib/dashboard/lastLook";
import { noteUserStageChange } from "@/lib/dashboard/lastLookStore";
import {
  deadlineChangeRequest,
  permanentDeleteRequest,
  removeFromBoardRequest,
  restoreToBoardRequest,
  roleChangeRequest,
  statusChangeRequest,
  type ProxyRequest,
} from "@/lib/dashboard/rowActions";
import { removedPagePath } from "@/lib/applications/removed";
import { publishAmbientPulse } from "@/lib/shell/ambient-bus";
import type { Application } from "@/lib/dashboard/summary";

/** What a row mutation came back with. */
export interface SendResult {
  ok: boolean;
  /** The backend's own reason, when it gave one. */
  detail?: string;
  /** The status the server says the row now holds, when it echoed one. */
  status?: string;
}

/**
 * One page of removed rows. `total` is the backend's full count under the same
 * predicate — never the length of `applications` — so the panel's "1–10 of 47"
 * describes the account rather than the page that happened to load.
 */
export interface RemovedPage {
  ok: boolean;
  applications: Application[];
  total: number;
  /** The backend's own reason, when it gave one. */
  detail?: string;
}

/** Row-level operations the board's cards and detail sheet perform. */
export interface BoardTransport {
  changeStatus(id: number, status: string): Promise<SendResult>;
  /** Set (`ISO datetime`) or clear (`null`) the row's deadline — always a
   *  user write, so the backend marks it `due_source: "user"` and sync
   *  never overwrites it. */
  setDeadline(id: number, dueAt: string | null): Promise<SendResult>;
  /** Set (a title) or clear (`null`) the row's role — issue #72. Always a user
   *  write, so the backend marks it `position_source: "user"`; the sync could
   *  not have supplied one anyway, and now may not overwrite this one either. */
  setRole(id: number, role: string | null): Promise<SendResult>;
  /** The RECOVERABLE removal ("Not an application") — never the hard delete. */
  dismiss(id: number): Promise<SendResult>;
  /**
   * The way back from `dismiss`, for the Undo the removal toast carries (#511).
   *
   * `SyncTransport` already has a `restore`, for the rows a REBUILD removed,
   * and this is deliberately not a call across to it: the two are separate
   * seams with separate demo implementations, and a card that reached into the
   * sync transport would make every mount of `ApplicationRow` depend on one.
   * It answers a full `SendResult`, unlike the sync side's boolean, because a
   * failed restore is a toast the reader must be able to act on and the
   * backend's own reason belongs in it.
   */
  restore(id: number): Promise<SendResult>;
  /**
   * One page of the rows that are OFF the board — what "Removed rows" reads
   * (#921).
   *
   * ON THE TRANSPORT, not a `fetch` inside the panel, and that placement is
   * what makes the feature testable at all. The e2e suite has no Supabase
   * session, so every board path it can execute runs on /demo against the
   * fixture transport; a panel that issued its own request would be a surface
   * CI can render and can never drive. Here the demo answers from its own
   * store, and "remove a row, wait out the window, find it, put it back" runs
   * end to end in a browser.
   *
   * `page` is 1-based, matching the backend. The pure half of the request —
   * the `dismissed` flag that separates this list from the board — lives in
   * `lib/applications/removed.ts`, because it is the one part of this path a
   * browser test cannot reach.
   */
  removed(page: number): Promise<RemovedPage>;
  /** The hard delete — the one behind a confirmation. */
  deleteRow(id: number): Promise<SendResult>;
  /** The application plus the mail behind it (`GET /api/applications/{id}` shape). */
  detail(id: number): Promise<{ ok: boolean; body: unknown }>;
}

/** What a sync/rebuild request resolved to, before interpretation. */
export interface SyncEnvelope {
  ok: boolean;
  status: number;
  body: unknown;
}

export interface SyncTransport {
  /**
   * `live` talks to Gmail through the proxy. `simulated` (the demo) runs the
   * identical SyncBar state machine against fixture outcomes — the UI states
   * one honest frame ("simulated account · nothing is read") instead of the
   * recency line, and keeps its rebuild memory under a separate key so a
   * signed-in owner visiting /demo never pollutes their real record.
   */
  mode: "live" | "simulated";
  sync(body: Record<string, unknown>): Promise<SyncEnvelope>;
  /** Restore one row a rebuild removed. True on success. */
  restore(id: number): Promise<boolean>;
}

async function send(req: ProxyRequest): Promise<SendResult> {
  try {
    const res = await fetch(req.path, {
      method: req.method,
      ...(req.body
        ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(req.body) }
        : {}),
    });
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown; status?: unknown };
    return {
      ok: res.ok,
      detail: typeof body.detail === "string" ? body.detail : undefined,
      status: typeof body.status === "string" ? body.status : undefined,
    };
  } catch {
    return { ok: false };
  }
}

/** The default: the same-origin proxy routes (JWT stays server-side). */
export const liveBoardTransport: BoardTransport = {
  async changeStatus(id, status) {
    const result = await send(statusChangeRequest(id, status));
    // A move the USER made is not news. Every path that changes a stage —
    // drag, the card's select, the detail sheet's — funnels through here, so
    // folding it into the change ledger's baseline in one place stops the
    // ledger reporting the reader's own drag back at them. A failed write
    // changes nothing, so it folds nothing.
    if (result.ok) noteUserStageChange(LAST_LOOK_KEY, id, result.status ?? status);
    if (result.ok) invalidateDetail(id);
    // A stage that moved is the rail's business too: the ambient field
    // (ambient-bus) surges on real changes, and every stage write funnels
    // through here — so this one publish covers drag, the card's select and
    // the detail sheet alike.
    if (result.ok) publishAmbientPulse(1);
    return result;
  },
  // Every row-scoped write drops that row's cached detail on success, so the
  // next open re-reads a trail its own tab just changed. A failed write
  // changed nothing and invalidates nothing.
  async setDeadline(id, dueAt) {
    const result = await send(deadlineChangeRequest(id, dueAt));
    if (result.ok) invalidateDetail(id);
    return result;
  },
  async setRole(id, role) {
    const result = await send(roleChangeRequest(id, role));
    if (result.ok) invalidateDetail(id);
    return result;
  },
  async dismiss(id) {
    const result = await send(removeFromBoardRequest(id));
    if (result.ok) invalidateDetail(id);
    return result;
  },
  async restore(id) {
    const result = await send(restoreToBoardRequest(id));
    if (result.ok) invalidateDetail(id);
    return result;
  },
  /**
   * `cache: "no-store"`, like `detail` and the sync: a reader opens this
   * BECAUSE the board just changed under them, and a page served from bfcache
   * or a router cache would answer with the set as it stood before the removal
   * they are looking for.
   */
  async removed(page) {
    try {
      const res = await fetch(removedPagePath(page), { cache: "no-store" });
      const body = (await res.json().catch(() => ({}))) as {
        applications?: unknown;
        total?: unknown;
        detail?: unknown;
      };
      // Shape-checked rather than cast. Everything here arrives from the wire,
      // and a panel that mapped over a non-array would throw inside a render —
      // in the one surface whose whole job is to be reachable when something
      // has already gone wrong.
      return {
        ok: res.ok && Array.isArray(body.applications),
        applications: Array.isArray(body.applications) ? (body.applications as Application[]) : [],
        total: typeof body.total === "number" ? body.total : 0,
        detail: typeof body.detail === "string" ? body.detail : undefined,
      };
    } catch {
      return { ok: false, applications: [], total: 0 };
    }
  },
  async deleteRow(id) {
    const result = await send(permanentDeleteRequest(id));
    if (result.ok) invalidateDetail(id);
    return result;
  },
  /**
   * Served from the in-tab cache inside its 30 s window — reopening a row, or
   * ↑/↓-traversing back to one, stops re-paying the measured 820–850 ms
   * origin round-trip (#203 §7). See `lib/dashboard/detailCache.ts` for the
   * trade and every invalidation path. The demo transport neither reads nor
   * writes this cache; its fixture reads are already instant.
   */
  async detail(id) {
    const cached = readCachedDetail(id);
    if (cached !== null) return { ok: true, body: cached };
    try {
      const res = await fetch(`/api/applications/${id}`, { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (res.ok) cacheDetail(id, body);
      return { ok: res.ok, body };
    } catch {
      return { ok: false, body: {} };
    }
  },
};

export const liveSyncTransport: SyncTransport = {
  mode: "live",
  async sync(body) {
    try {
      const res = await fetch("/api/gmail/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      // A sync/rebuild can create rows and append to ANY application's
      // verdict trail, so no per-id invalidation can be right here.
      if (res.ok) clearDetailCache();
      return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, status: 0, body: {} };
    }
  },
  async restore(id) {
    try {
      const res = await fetch(`/api/applications/${id}/restore`, { method: "POST" });
      if (res.ok) invalidateDetail(id);
      return res.ok;
    } catch {
      return false;
    }
  },
};
