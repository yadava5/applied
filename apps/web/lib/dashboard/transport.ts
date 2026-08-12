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
import { LAST_LOOK_KEY } from "@/lib/dashboard/lastLook";
import { noteUserStageChange } from "@/lib/dashboard/lastLookStore";
import {
  deadlineChangeRequest,
  permanentDeleteRequest,
  removeFromBoardRequest,
  statusChangeRequest,
  type ProxyRequest,
} from "@/lib/dashboard/rowActions";

/** What a row mutation came back with. */
export interface SendResult {
  ok: boolean;
  /** The backend's own reason, when it gave one. */
  detail?: string;
  /** The status the server says the row now holds, when it echoed one. */
  status?: string;
}

/** Row-level operations the board's cards and detail sheet perform. */
export interface BoardTransport {
  changeStatus(id: number, status: string): Promise<SendResult>;
  /** Set (`ISO datetime`) or clear (`null`) the row's deadline — always a
   *  user write, so the backend marks it `due_source: "user"` and sync
   *  never overwrites it. */
  setDeadline(id: number, dueAt: string | null): Promise<SendResult>;
  /** The RECOVERABLE removal ("Not an application") — never the hard delete. */
  dismiss(id: number): Promise<SendResult>;
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
    return result;
  },
  setDeadline: (id, dueAt) => send(deadlineChangeRequest(id, dueAt)),
  dismiss: (id) => send(removeFromBoardRequest(id)),
  deleteRow: (id) => send(permanentDeleteRequest(id)),
  async detail(id) {
    try {
      const res = await fetch(`/api/applications/${id}`, { cache: "no-store" });
      return { ok: res.ok, body: await res.json().catch(() => ({})) };
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
      return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, status: 0, body: {} };
    }
  },
  async restore(id) {
    try {
      const res = await fetch(`/api/applications/${id}/restore`, { method: "POST" });
      return res.ok;
    } catch {
      return false;
    }
  },
};
