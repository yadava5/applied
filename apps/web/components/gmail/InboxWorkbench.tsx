"use client";

import { Bell, Loader2, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { selectClass } from "@/components/ui/formStyles";
import {
  buildInboxParams,
  CATEGORY_META,
  CATEGORY_ORDER,
  COUNT_OPTIONS,
  DEFAULT_FILTERS,
  JOB_RELATED_CATEGORIES,
  PAGE_SIZE,
  RANGE_OPTIONS,
  type FetchCount,
  type InboxFilters,
  type InboxPage,
  type InboxVerdict,
  type PipelineAnalysis,
  type RangeValue,
  type ScopeValue,
} from "@/lib/gmail/types";
import { cn } from "@/lib/utils";

/**
 * The high-volume, filterable inbox mine.
 *
 * Fetches are server-paginated: this component loops `/api/gmail/inbox`
 * (each call bounded to keep the serverless function inside its time budget),
 * accumulating pages with a live progress tally until it reaches the chosen
 * count or Gmail runs out. It then posts the accumulated set to
 * `/api/gmail/pipeline` for the whole-set category summary + "no response /
 * follow-up" flags. Token/`BACKEND_API_URL` stay server-side (the proxy routes
 * add the JWT from cookies); the client only ever sees verdict metadata.
 */

type Phase = "loading" | "ready" | "not_connected" | "auth" | "error";

interface FetchState {
  phase: Phase;
  fetched: number;
  target: number;
  errorStatus?: number;
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex rounded-lg border border-line-soft bg-surface p-0.5"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              active ? "bg-strong text-background" : "text-muted hover:text-strong",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

function VerdictRow({ v }: { v: InboxVerdict }) {
  const meta = CATEGORY_META[v.category] ?? { label: v.category, dot: "bg-dim" };
  return (
    <li className="flex items-start justify-between gap-4 border-b border-line-soft px-1 py-3 last:border-b-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-strong">{v.subject}</p>
        <p className="truncate font-mono text-[11px] text-dim">
          {v.sender_name ? `${v.sender_name} · ` : ""}
          {v.sender_email}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3 text-right">
        <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
          {meta.label}
        </span>
        <span className="tabular w-10 font-mono text-[11px] text-dim">{pct(v.confidence)}</span>
        {v.needs_review ? (
          <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-review">
            review
          </span>
        ) : (
          <span className="w-[52px]" aria-hidden />
        )}
      </div>
    </li>
  );
}

function SkeletonRow() {
  return (
    <li className="flex items-center justify-between gap-4 border-b border-line-soft px-1 py-3 last:border-b-0">
      <div className="min-w-0 flex-1 space-y-2">
        <div className="h-3 w-2/3 animate-pulse rounded bg-surface-2" />
        <div className="h-2.5 w-1/3 animate-pulse rounded bg-surface-2" />
      </div>
      <div className="h-3 w-16 animate-pulse rounded bg-surface-2" />
    </li>
  );
}

/**
 * Per-visit snapshot cache (tab `sessionStorage`), keyed by the active filters.
 *
 * Every navigation to /inbox remounts this component; without a cache the mount
 * effect re-mined Gmail on each visit — many paged `/api/gmail/inbox` calls plus
 * a purge/rebuild `/api/gmail/sync` — which is the "re-scans on every visit" bug.
 * Instead we persist the last successful mine and, on remount with the SAME
 * filters, hydrate from it: repeat visits are instant and hit neither Gmail nor
 * the classifier. Changing a filter or pressing Refresh still re-mines (and
 * rewrites the snapshot); a short TTL bounds staleness. Session-scoped only —
 * nothing touches disk, and the JWT is still verified on any real fetch.
 */
const SNAPSHOT_KEY = "applied:inbox:snapshot:v1";
const SNAPSHOT_TTL_MS = 15 * 60 * 1000; // 15 minutes

interface InboxSnapshot {
  sig: string;
  savedAt: number;
  verdicts: InboxVerdict[];
  analysis: PipelineAnalysis | null;
  fetched: number;
  target: number;
}

/** The fetch inputs that define a distinct mine — a snapshot is valid only for its own. */
function filtersSig(f: InboxFilters): string {
  return `${f.range}|${f.scope}|${f.count}`;
}

function readSnapshot(sig: string): InboxSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return null;
    const snap = JSON.parse(raw) as InboxSnapshot;
    if (snap.sig !== sig || Date.now() - snap.savedAt > SNAPSHOT_TTL_MS) return null;
    return snap;
  } catch {
    return null;
  }
}

function writeSnapshot(snap: InboxSnapshot): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snap));
  } catch {
    // Quota / serialization failure — the cache is a nicety, never required.
  }
}

export function InboxWorkbench({ email }: { email?: string | null }) {
  const [filters, setFilters] = useState<InboxFilters>(DEFAULT_FILTERS);
  const [verdicts, setVerdicts] = useState<InboxVerdict[]>([]);
  const [analysis, setAnalysis] = useState<PipelineAnalysis | null>(null);
  const [state, setState] = useState<FetchState>({
    phase: "loading",
    fetched: 0,
    target: DEFAULT_FILTERS.count,
  });

  // View filters (client-side, no refetch).
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [jobOnly, setJobOnly] = useState(false);

  const runIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  // Distinguishes the first mount (may hydrate from cache) from a later
  // filters change (always a real, user-initiated re-mine).
  const didInitRef = useRef(false);

  const run = useCallback(async (f: InboxFilters) => {
    const runId = ++runIdRef.current;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const target = f.count;

    setVerdicts([]);
    setAnalysis(null);
    setState({ phase: "loading", fetched: 0, target });

    const acc: InboxVerdict[] = [];
    let token: string | null | undefined;

    try {
      while (acc.length < target) {
        const pageSize = Math.min(PAGE_SIZE, target - acc.length);
        const qs = buildInboxParams({ filters: f, pageSize, pageToken: token });
        const res = await fetch(`/api/gmail/inbox?${qs}`, {
          cache: "no-store",
          signal: ac.signal,
        });
        if (runId !== runIdRef.current) return;
        if (res.status === 409) {
          setState({ phase: "not_connected", fetched: acc.length, target });
          return;
        }
        if (res.status === 401) {
          setState({ phase: "auth", fetched: acc.length, target, errorStatus: 401 });
          return;
        }
        if (!res.ok) {
          setState({ phase: "error", fetched: acc.length, target, errorStatus: res.status });
          return;
        }
        const page = (await res.json()) as InboxPage;
        acc.push(...page.verdicts);
        if (runId !== runIdRef.current) return;
        setVerdicts([...acc]);
        setState({ phase: "loading", fetched: acc.length, target });
        token = page.next_page_token;
        if (!token || page.verdicts.length === 0) break;
      }

      // Reduce to the minimal shape the pipeline + sync endpoints need.
      const pipelineItems = acc.map((v) => ({
        message_id: v.message_id,
        category: v.category,
        sender_email: v.sender_email,
        subject: v.subject,
        sender_name: v.sender_name,
        received_at: v.received_at,
      }));

      // Whole-set analysis (category summary + follow-up flags).
      const analysisRes = await fetch("/api/gmail/pipeline", {
        method: "POST",
        cache: "no-store",
        signal: ac.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: pipelineItems }),
      });
      if (runId !== runIdRef.current) return;
      let analysisData: PipelineAnalysis | null = null;
      if (analysisRes.ok) {
        analysisData = (await analysisRes.json()) as PipelineAnalysis;
        setAnalysis(analysisData);
      }
      setState({ phase: "ready", fetched: acc.length, target });

      // Persist this mine so a remount with the same filters (e.g. navigating
      // Inbox → Dashboard → Inbox) hydrates instantly instead of re-hitting Gmail.
      writeSnapshot({
        sig: filtersSig(f),
        savedAt: Date.now(),
        verdicts: acc,
        analysis: analysisData,
        fetched: acc.length,
        target,
      });

      // Opportunistically persist the mined pipeline so the dashboard shows the
      // real board. Fire-and-forget: the inbox view never blocks on it, the
      // backend upsert is idempotent, and mode:"additive" means relaying a
      // narrow mine never wipes applications a broader one already found.
      void fetch("/api/gmail/sync", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: pipelineItems, mode: "additive" }),
      }).catch(() => {});
    } catch {
      if (ac.signal.aborted || runId !== runIdRef.current) return;
      setState({ phase: "error", fetched: acc.length, target });
    }
  }, []);

  // On first mount, serve a fresh cached snapshot for these filters if we have
  // one — this is what stops the re-scan on every visit. Only mine Gmail when
  // there's nothing cached (first-ever visit) or the user changed a filter;
  // rapid toggling still collapses into a single debounced mine. The manual
  // Refresh button calls `run` directly and always re-mines. The state update
  // runs inside the timeout (not synchronously in the effect body) so hydration
  // never triggers a cascading render.
  useEffect(() => {
    const firstMount = !didInitRef.current;
    didInitRef.current = true;
    const t = setTimeout(
      () => {
        if (firstMount) {
          const snap = readSnapshot(filtersSig(filters));
          if (snap) {
            setVerdicts(snap.verdicts);
            setAnalysis(snap.analysis);
            setState({ phase: "ready", fetched: snap.fetched, target: snap.target });
            return;
          }
        }
        void run(filters);
      },
      firstMount ? 0 : 300,
    );
    return () => clearTimeout(t);
  }, [filters, run]);

  const summary = useMemo(() => {
    if (analysis) return analysis.category_summary;
    const s: Record<string, number> = {};
    for (const v of verdicts) s[v.category] = (s[v.category] ?? 0) + 1;
    return s;
  }, [analysis, verdicts]);

  const followUps = analysis?.follow_ups ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return verdicts.filter((v) => {
      if (jobOnly && !JOB_RELATED_CATEGORIES.includes(v.category)) return false;
      if (activeCategory && v.category !== activeCategory) return false;
      if (q) {
        const hay = `${v.subject} ${v.sender_email} ${v.sender_name ?? ""} ${v.company}`;
        if (!hay.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [verdicts, search, activeCategory, jobOnly]);

  const jobRelatedTotal = useMemo(
    () => JOB_RELATED_CATEGORIES.reduce((sum, c) => sum + (summary[c] ?? 0), 0),
    [summary],
  );

  const loading = state.phase === "loading";
  const progressPct =
    state.target > 0 ? Math.min(100, Math.round((state.fetched / state.target) * 100)) : 0;

  // --- Runtime failure states (token revoked mid-session, backend down) -----
  if (state.phase === "not_connected") {
    return (
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <h2 className="text-base font-medium text-strong">Connect Gmail to fill this inbox</h2>
        <p className="mt-1.5 text-sm text-muted">
          Read-only, on Google&apos;s own consent screen. The classifier labels your job-search mail —
          it <span className="text-strong">cannot</span> send, delete, or modify anything.
        </p>
        <ConnectGmailButton className="mt-4" />
      </div>
    );
  }

  if (state.phase === "auth") {
    return (
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <h2 className="text-base font-medium text-strong">Your Gmail session needs a refresh</h2>
        <p className="mt-1.5 text-sm text-muted">
          The connection expired or was revoked. Reconnect Gmail to keep mining your pipeline.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <ConnectGmailButton />
          <Link
            href="/login?redirect=/inbox"
            className="font-mono text-[11px] text-dim underline-offset-4 hover:text-strong hover:underline"
          >
            or sign in again →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* --- Filter bar --------------------------------------------------- */}
      <div className="rounded-xl border border-line-soft bg-surface p-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <label className="flex flex-col gap-1.5">
            <span className="label-mono">age</span>
            <Segmented<RangeValue>
              ariaLabel="Time range"
              options={RANGE_OPTIONS}
              value={filters.range}
              onChange={(range) => setFilters((f) => ({ ...f, range }))}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="label-mono">where</span>
            <Segmented<ScopeValue>
              ariaLabel="Mail scope"
              options={[
                { value: "inbox", label: "Inbox" },
                { value: "anywhere", label: "All mail" },
              ]}
              value={filters.scope}
              onChange={(scope) => setFilters((f) => ({ ...f, scope }))}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="label-mono">fetch</span>
            <select
              aria-label="Number of messages to fetch"
              className={cn(selectClass, "w-28 py-1.5 text-xs")}
              value={filters.count}
              onChange={(e) =>
                setFilters((f) => ({ ...f, count: Number(e.target.value) as FetchCount }))
              }
            >
              {COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n.toLocaleString()} msgs
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => void run(filters)}
            disabled={loading}
            className="ml-auto inline-flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-40"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
            {loading ? "Fetching…" : "Refresh"}
          </button>
        </div>

        {/* progress while paging */}
        {loading ? (
          <div className="mt-4">
            <div className="flex items-center justify-between font-mono text-[11px] text-dim">
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                mining {filters.scope === "anywhere" ? "all mail" : "inbox"}
                {filters.range !== "all" ? ` · last ${filters.range} mo` : ""}
              </span>
              <span className="tabular">
                {state.fetched.toLocaleString()} / {state.target.toLocaleString()}
              </span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-viz-embeddings transition-all duration-300"
                style={{ width: `${Math.max(4, progressPct)}%` }}
              />
            </div>
          </div>
        ) : (
          <p className="mt-3 font-mono text-[11px] text-dim">
            {email ? `${email} · ` : ""}
            {state.fetched.toLocaleString()} scanned · {jobRelatedTotal.toLocaleString()} job-related
          </p>
        )}
      </div>

      {/* --- Needs follow-up (ghosting) ----------------------------------- */}
      {followUps.length > 0 ? (
        <div className="rounded-xl border border-review/40 bg-surface p-5">
          <h2 className="flex items-center gap-2 text-base font-medium text-strong">
            <Bell className="h-4 w-4 text-review" aria-hidden />
            Needs follow-up ({followUps.length})
          </h2>
          <p className="mt-1 text-sm text-muted">
            You applied but never heard back — no interview, assessment, offer, or rejection since.
          </p>
          <ul className="mt-3 space-y-2">
            {followUps.map((f) => (
              <li
                key={f.message_id}
                className="flex items-center justify-between gap-4 rounded-lg border border-line-soft px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm text-strong">
                    <span className="font-medium capitalize">{f.company}</span>
                    <span className="text-dim"> · {f.subject}</span>
                  </p>
                </div>
                <span className="shrink-0 font-mono text-[11px] text-review">
                  {f.days_since}d silent
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* --- Category summary + view filters ------------------------------ */}
      <div className="rounded-xl border border-line-soft bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            aria-pressed={activeCategory === null}
            className={cn(
              "rounded-full border px-3 py-1 font-mono text-[11px] transition-colors",
              activeCategory === null
                ? "border-line-strong text-strong"
                : "border-line-soft text-dim hover:text-muted",
            )}
          >
            all {verdicts.length.toLocaleString()}
          </button>
          {CATEGORY_ORDER.filter((c) => (summary[c] ?? 0) > 0).map((c) => {
            const meta = CATEGORY_META[c];
            const active = activeCategory === c;
            return (
              <button
                key={c}
                type="button"
                onClick={() => setActiveCategory(active ? null : c)}
                aria-pressed={active}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] transition-colors",
                  active
                    ? "border-line-strong text-strong"
                    : "border-line-soft text-muted hover:text-strong",
                )}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
                {meta.label} {summary[c] ?? 0}
              </button>
            );
          })}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-line-soft pt-4">
          <div className="relative flex-1 basis-48">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dim"
              aria-hidden
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search subject, sender, company…"
              aria-label="Search messages"
              className="w-full rounded-lg border border-line bg-surface-2 py-1.5 pl-8 pr-3 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong"
            />
          </div>
          <label className="inline-flex cursor-pointer select-none items-center gap-2 font-mono text-[11px] text-muted">
            <input
              type="checkbox"
              checked={jobOnly}
              onChange={(e) => setJobOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--viz-embeddings)]"
            />
            job-related only
          </label>
        </div>
      </div>

      {/* --- Verdict list ------------------------------------------------- */}
      {loading && verdicts.length === 0 ? (
        <ul className="rounded-xl border border-line-soft bg-surface px-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonRow key={i} />
          ))}
        </ul>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line-soft bg-surface p-8 text-center text-sm text-muted">
          {verdicts.length === 0
            ? "No messages matched this range. Widen the age window or switch to All mail."
            : "No messages match these view filters."}
        </div>
      ) : (
        <ul className="rounded-xl border border-line-soft bg-surface px-3">
          {filtered.map((v) => (
            <VerdictRow key={v.message_id} v={v} />
          ))}
        </ul>
      )}

      {state.phase === "error" ? (
        <p className="font-mono text-[11px] text-review">
          The mail backend hiccuped{state.errorStatus ? ` (${state.errorStatus})` : ""} — press
          Refresh to try again.
        </p>
      ) : null}
    </div>
  );
}
