"use client";

import { Bell, Loader2, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { MailSnippet, OpenInGmail } from "@/components/mail/MailPreview";
import { ReclassifyControl } from "@/components/mail/ReclassifyControl";
import { selectClass } from "@/components/ui/formStyles";
import { Segmented } from "@/components/ui/Segmented";
import { GateMeter } from "@/components/viz/GateMeter";
import { shortDate } from "@/lib/dashboard/dates";
import {
  applyVerdictCorrection,
  scanMessagePayload,
  UNSTORABLE_ROW_NOTE,
  verdictShowsConfidence,
} from "@/lib/gmail/scan-correction";
import { filedSummary } from "@/lib/gmail/sync-state";
import {
  scanTransport,
  toPipelineItems,
  type ClassifyFn,
  type ScanMode,
} from "@/lib/gmail/transport";
import {
  buildInboxParams,
  categoryChips,
  CATEGORY_META,
  chipTotal,
  COUNT_OPTIONS,
  DEFAULT_FILTERS,
  JOB_RELATED_CATEGORIES,
  PAGE_SIZE,
  RANGE_OPTIONS,
  type CategorySummary,
  type FetchCount,
  type InboxFilters,
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
 *
 * Mining and FILING are separate, and both are visible. The mine is read-only;
 * an explicit "File N into Applications" control persists it and then reports
 * what the sync actually did ("3 filed, 1 already known"). Previously this
 * component relayed the mine to `/gmail/sync` fire-and-forget, so the one thing
 * the user wanted — their board filled from the mail they were looking at —
 * happened invisibly or not at all, and the only visible route to a filled
 * board was the dashboard's full re-scan.
 */

type Phase = "loading" | "ready" | "not_connected" | "auth" | "error";

interface FetchState {
  phase: Phase;
  fetched: number;
  target: number;
  errorStatus?: number;
}

/** The "file these into my pipeline" action's own state — never the mine's. */
interface FileState {
  phase: "idle" | "filing" | "done" | "error";
  /** What the sync reported, in the user's terms ("3 filed, 1 already known"). */
  note: string | null;
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

/**
 * One classified message — the verdict rendered as the product's own visual,
 * not debug output: category chip, the confidence drawn against the 0.85
 * auto-file gate (the landing DecisionTrace's meter, via `GateMeter`), the
 * percentage in the cleared/held hue, and the receipt date. Fixed column
 * widths keep the meters aligned down the list so confidence reads as a
 * column, not a scatter.
 *
 * It also carries the message itself — a one-line preview and a link that
 * opens it in Gmail, both the filed ledger's own (`MailSnippet` /
 * `OpenInGmail`), shared rather than rewritten. Without them this view asked
 * the reader to confirm or overrule a verdict about a message they could
 * neither read nor reach: "how can i classify when i don't even know the
 * content or don't have the link to look at it". A row whose snippet or link
 * is null renders neither, so nothing here is ever a blank line or a dead
 * control.
 *
 * Every row carries a CORRECTION, which is what this view was missing. It used
 * to be read-only: an assessment email labelled "other" at 0% had nothing to
 * press, and filing could not rescue it either — the sync drops everything
 * below the 0.70 review floor, so that message was never stored and so never
 * correctable anywhere. The control sends the message's own metadata with the
 * correction, which is what lets the backend store it first (see
 * `scanMessagePayload`). A row the mine could not date cannot be stored at
 * all, and says so rather than offering a control that would fail.
 */
function VerdictRow({
  v,
  onCorrected,
  classify,
}: {
  v: InboxVerdict;
  onCorrected: (messageId: string, category: string) => void;
  classify: ClassifyFn;
}) {
  const meta = CATEGORY_META[v.category] ?? {
    label: v.category,
    dot: "bg-dim",
  };
  const payload = scanMessagePayload(v);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-soft px-1 py-3 last:border-b-0">
      {/* basis-full on mobile gives the subject its own line; sm+ restores the
          single-row layout (same rule as the landing trace rows). */}
      <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
        <p className="truncate text-sm font-medium text-strong">{v.subject}</p>
        <p className="truncate text-xs text-dim">
          {v.sender_name ? `${v.sender_name} · ` : ""}
          {v.sender_email}
        </p>
        <MailSnippet snippet={v.snippet} />
      </div>
      <span className="inline-flex w-24 items-center gap-1.5 text-xs text-muted">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} aria-hidden />
        <span className="truncate">{meta.label}</span>
      </span>
      {/* The meter and the percentage belong to the CLASSIFIER's verdict, so
          they are drawn only while the verdict on this row is still the
          classifier's (`verdictShowsConfidence`). The slots keep their widths
          so the meters stay a column rather than a scatter, and the em-dash
          says "no figure" where a percentage would otherwise be read as
          certainty about the reader's own label. */}
      {verdictShowsConfidence(v) ? (
        <>
          <GateMeter confidence={v.confidence} className="hidden sm:inline-block" />
          <span
            className="tabular w-10 text-right font-mono text-[11px]"
            style={{ color: v.needs_review ? "var(--amber)" : "var(--green)" }}
          >
            {pct(v.confidence)}
          </span>
        </>
      ) : (
        <>
          <span className="hidden h-1 w-14 shrink-0 sm:inline-block" aria-hidden />
          <span className="tabular w-10 text-right font-mono text-[11px] text-dim">—</span>
        </>
      )}
      {v.needs_review ? (
        <span className="rounded-full border border-review/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-review">
          review
        </span>
      ) : (
        <span className="w-[52px]" aria-hidden />
      )}
      <span className="tabular hidden w-12 shrink-0 text-right font-mono text-[10px] text-dim md:inline">
        {v.received_at ? shortDate(v.received_at) : ""}
      </span>
      <OpenInGmail href={v.gmail_link} subject={v.subject} />
      <span className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1">
        {v.user_corrected ? <span className="text-[11px] text-dim">corrected by you</span> : null}
        {payload ? (
          <ReclassifyControl
            messageId={v.message_id}
            subject={v.subject}
            company={v.company || null}
            message={payload}
            classify={classify}
            onCorrected={(category) => onCorrected(v.message_id, category)}
          />
        ) : (
          <span className="text-[11px] text-dim">{UNSTORABLE_ROW_NOTE}</span>
        )}
      </span>
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
 * effect re-mined Gmail on each visit — many paged `/api/gmail/inbox` calls, and
 * (until filing became explicit) an unreported `/api/gmail/sync` behind them —
 * which is the "re-scans on every visit" bug. The snapshot also survives the
 * `router.refresh()` the file action triggers, so filing cannot cause a re-mine.
 * Instead we persist the last successful mine and, on remount with the SAME
 * filters, hydrate from it: repeat visits are instant and hit neither Gmail nor
 * the classifier. Changing a filter or pressing Refresh still re-mines (and
 * rewrites the snapshot); a short TTL bounds staleness. Session-scoped only —
 * nothing touches disk, and the JWT is still verified on any real fetch.
 */
/**
 * BUMP THE VERSION whenever the stored verdict shape changes. A snapshot is
 * rehydrated verbatim on remount, so a reader mid-session when a deploy lands
 * keeps being served the OLD shape for the rest of the TTL — with every test
 * and every gate green, because nothing on the server can see it. `v1`
 * snapshots predate `snippet`/`gmail_link`: left on `v1` this change would
 * have shipped and still shown that reader a row with no preview and no way
 * to open the message, which is the complaint it exists to fix. An unknown
 * key simply misses, so the bump costs one re-mine and nothing else.
 */
const SNAPSHOT_KEY = "applied:inbox:snapshot:v2";
const SNAPSHOT_TTL_MS = 15 * 60 * 1000; // 15 minutes

interface InboxSnapshot {
  sig: string;
  savedAt: number;
  verdicts: InboxVerdict[];
  analysis: PipelineAnalysis | null;
  /** The analysis call failed for this mine — a null `analysis` alone cannot
   *  say whether it failed or was simply never reached, and the follow-up
   *  panel must not vanish silently on a rehydrated mine either. */
  analysisFailed?: boolean;
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

/**
 * Fold a correction into the cached mine, keeping `savedAt` where it was.
 *
 * Without this a correction lives only in React state, and this component
 * rehydrates from the snapshot on every remount — so navigating Inbox →
 * Dashboard → Inbox would put the classifier's rejected verdict straight back
 * on screen, which is the "did my click do anything?" complaint with an extra
 * step. `router.refresh()` cannot cover it: the mine is client state the
 * server tree knows nothing about.
 *
 * `savedAt` is preserved deliberately — a correction is not a fresh read of
 * Gmail, and re-stamping it would extend the staleness window on data that is
 * exactly as old as it was a moment ago.
 */
function patchSnapshot(
  sig: string,
  patch: { verdicts: InboxVerdict[]; summary: CategorySummary },
): void {
  const existing = readSnapshot(sig);
  if (!existing) return;
  writeSnapshot({
    ...existing,
    verdicts: patch.verdicts,
    analysis: existing.analysis
      ? { ...existing.analysis, category_summary: patch.summary }
      : existing.analysis,
  });
}

export function InboxWorkbench({
  email,
  mode = "live",
}: {
  email?: string | null;
  /** Which transport the mine and its corrections run on. `demo` is the
   *  public `/demo/scan` twin — the same component over fixtures, which is the
   *  only way this view is reachable without a session and a linked mailbox. */
  mode?: ScanMode;
}) {
  const router = useRouter();
  const transport = useMemo(() => scanTransport(mode), [mode]);
  const [filters, setFilters] = useState<InboxFilters>(DEFAULT_FILTERS);
  const [verdicts, setVerdicts] = useState<InboxVerdict[]>([]);
  const [analysis, setAnalysis] = useState<PipelineAnalysis | null>(null);
  /** The whole-set analysis failed for the current mine — the ghosting panel
   *  says so instead of not rendering (an absent panel reads as "nobody has
   *  ghosted you", which is a claim we cannot make without the analysis). */
  const [analysisFailed, setAnalysisFailed] = useState(false);
  const [state, setState] = useState<FetchState>({
    phase: "loading",
    fetched: 0,
    target: DEFAULT_FILTERS.count,
  });
  const [filing, setFiling] = useState<FileState>({
    phase: "idle",
    note: null,
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

  const run = useCallback(
    async (f: InboxFilters) => {
      const runId = ++runIdRef.current;
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      const target = f.count;

      setVerdicts([]);
      setAnalysis(null);
      setAnalysisFailed(false);
      setState({ phase: "loading", fetched: 0, target });
      // A new mine invalidates the last filing report — it described a different set.
      setFiling({ phase: "idle", note: null });

      const acc: InboxVerdict[] = [];
      let token: string | null | undefined;

      try {
        while (acc.length < target) {
          const pageSize = Math.min(PAGE_SIZE, target - acc.length);
          const qs = buildInboxParams({
            filters: f,
            pageSize,
            pageToken: token,
          });
          const { status, page } = await transport.fetchPage(qs, ac.signal);
          if (runId !== runIdRef.current) return;
          if (status === 409) {
            setState({ phase: "not_connected", fetched: acc.length, target });
            return;
          }
          if (status === 401) {
            setState({
              phase: "auth",
              fetched: acc.length,
              target,
              errorStatus: 401,
            });
            return;
          }
          if (!page) {
            setState({
              phase: "error",
              fetched: acc.length,
              target,
              errorStatus: status,
            });
            return;
          }
          acc.push(...page.verdicts);
          if (runId !== runIdRef.current) return;
          setVerdicts([...acc]);
          setState({ phase: "loading", fetched: acc.length, target });
          token = page.next_page_token;
          if (!token || page.verdicts.length === 0) break;
        }

        const pipelineItems = toPipelineItems(acc);

        // Whole-set analysis (category summary + follow-up flags) — in its OWN
        // try/catch. The mine has already succeeded by this point, so a thrown
        // analysis fetch must not fall into the outer catch and mark the whole
        // mine failed: that would put a "we couldn't read your mail" banner over
        // a complete, correct verdict list (and skip the snapshot, re-mining
        // Gmail on the next visit). A failure here degrades to the per-verdict
        // category tally, with the follow-up panel saying it is unavailable.
        let analysisData: PipelineAnalysis | null = null;
        let analysisBroke = false;
        try {
          analysisData = await transport.analyze(pipelineItems, ac.signal);
          if (runId !== runIdRef.current) return;
          if (analysisData) {
            setAnalysis(analysisData);
          } else {
            analysisBroke = true;
          }
        } catch {
          // An abort is a newer mine taking over, not a failure.
          if (ac.signal.aborted || runId !== runIdRef.current) return;
          analysisBroke = true;
        }
        setAnalysisFailed(analysisBroke);
        setState({ phase: "ready", fetched: acc.length, target });

        // Persist this mine so a remount with the same filters (e.g. navigating
        // Inbox → Dashboard → Inbox) hydrates instantly instead of re-hitting Gmail.
        writeSnapshot({
          sig: filtersSig(f),
          savedAt: Date.now(),
          verdicts: acc,
          analysis: analysisData,
          analysisFailed: analysisBroke,
          fetched: acc.length,
          target,
        });

        // NOTE: the mine deliberately does NOT persist anything by itself. It
        // used to fire a `/api/gmail/sync` relay here and never report the
        // result, so a user could watch it scan 200 messages, read "applied 4",
        // and have no idea whether any of it reached their pipeline. Filing is
        // now the explicit action below, which says what actually happened.
      } catch {
        if (ac.signal.aborted || runId !== runIdRef.current) return;
        setState({ phase: "error", fetched: acc.length, target });
      }
    },
    [transport],
  );

  // On first mount, serve a fresh cached snapshot for these filters if we have
  // one — this is what stops the re-scan on every visit. Only mine Gmail when
  // there's nothing cached (first-ever visit) or the user changed a filter;
  // rapid toggling still collapses into a single debounced mine. The manual
  // Refresh button calls `run` directly and always re-mines. The state update
  // runs inside the timeout (not synchronously in the effect body) so hydration
  // never triggers a cascading render.
  //
  // THE FLAG IS BURNED INSIDE THE TIMEOUT, NOT IN THE EFFECT BODY, and that is
  // load-bearing. React StrictMode invokes an effect create → cleanup → create;
  // setting `didInitRef` at creation time marked the mount as "already done" on
  // the invocation whose timeout the cleanup then cleared, so the invocation
  // that actually survived saw `firstMount === false`, skipped the snapshot
  // read entirely, and re-mined Gmail — silently replacing a verdict the user
  // had corrected with the classifier's original one. Setting it inside the
  // callback means only a timeout that RAN counts as the mount having happened.
  //
  // Found by a dependency bump: Next 16.3.0 began applying StrictMode in dev
  // and `scan-correct.spec.ts`'s "the correction survives leaving the view and
  // coming back" went red on 16.3.0 while passing on 16.2.11 — measured, the
  // mount effect ran twice and the snapshot read never executed. Production
  // never double-invokes, so this was invisible in every production build and
  // to every user; it was one identity change away from not being (a
  // non-stable `run` or `filters`, React Compiler, any future double-invoke),
  // and losing a correction here is the "did my click do anything?" bug with
  // the user's own judgement thrown away.
  useEffect(() => {
    const firstMount = !didInitRef.current;
    const t = setTimeout(
      () => {
        didInitRef.current = true;
        if (firstMount) {
          const snap = readSnapshot(filtersSig(filters));
          if (snap) {
            setVerdicts(snap.verdicts);
            setAnalysis(snap.analysis);
            setAnalysisFailed(snap.analysisFailed === true);
            setState({
              phase: "ready",
              fetched: snap.fetched,
              target: snap.target,
            });
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

  /**
   * Fold an accepted correction back into the mine — row, counts, and cache.
   *
   * All three, because any one alone is a lie somewhere on the page. The row
   * alone leaves the chips reading the classifier's tally, and the chips only
   * exist for categories some message holds — so correcting the owner's
   * assessment email would still leave "assessment" with nowhere to appear,
   * which is the complaint. The counts here are usually the WHOLE-SET analysis
   * from `/gmail/pipeline`, not a tally of the rendered rows, so they have to
   * be moved deliberately rather than recomputed. And the snapshot, because
   * this component rehydrates from it on remount and would otherwise restore
   * the verdict the user just overruled.
   */
  const applyCorrection = useCallback(
    (messageId: string, category: string) => {
      const next = applyVerdictCorrection({ verdicts, summary }, messageId, category);
      if (!next.changed) return;
      setVerdicts(next.verdicts);
      // Only when there IS an analysis: without one `summary` is derived from
      // the verdicts above, so it has already moved.
      if (analysis) setAnalysis({ ...analysis, category_summary: next.summary });
      patchSnapshot(filtersSig(filters), {
        verdicts: next.verdicts,
        summary: next.summary,
      });
    },
    [analysis, filters, summary, verdicts],
  );

  /**
   * File the mined set into the pipeline — the action the inbox never had.
   *
   * Every message goes to the backend, not just the job-related ones: it is the
   * backend's roll-up that decides what becomes an application row and what
   * feeds the review queue, and `scanned` should reflect what we actually
   * looked at. `mode: "additive"` so relaying a narrow mine can never wipe
   * applications a broader scan already found, and the upsert is idempotent, so
   * pressing this twice is harmless. Deliberately NO `count`/`range` in the
   * body: either would make the backend treat this as a windowed request and
   * skip the incremental path.
   *
   * `router.refresh()` on success is what makes the sidebar's pipeline counts
   * and "last synced" catch up immediately. It reconciles the server tree
   * rather than remounting this component, so it cannot re-mine Gmail — and
   * even a remount would hydrate from the session snapshot written above.
   */
  const fileThese = useCallback(async () => {
    const items = toPipelineItems(verdicts);
    if (items.length === 0) return;

    setFiling({ phase: "filing", note: null });
    try {
      const res = await transport.file(items);
      if (!res.ok) {
        setFiling({
          phase: "error",
          note:
            res.status === 409
              ? "Gmail isn't connected — nothing was filed."
              : `Couldn't file these (${res.status}) — nothing was changed.`,
        });
        return;
      }
      setFiling({ phase: "done", note: filedSummary(res.counts) });
      router.refresh();
    } catch {
      setFiling({
        phase: "error",
        note: "Couldn't reach the server — nothing was filed.",
      });
    }
  }, [router, transport, verdicts]);

  const loading = state.phase === "loading";
  /** The MINE broke (Gmail/proxy). Distinct from `analysisFailed`, which is a
   *  successful mine whose whole-set analysis didn't answer. */
  const mineFailed = state.phase === "error";
  const progressPct =
    state.target > 0 ? Math.min(100, Math.round((state.fetched / state.target) * 100)) : 0;

  // --- Runtime failure states (token revoked mid-session, backend down) -----
  if (state.phase === "not_connected") {
    return (
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        {/* No scopes paragraph (#200): Google's consent screen states them at
            the moment of consent, and the page's standing /privacy link is
            the durable copy. */}
        <h2 className="text-base font-medium text-strong">Connect Gmail to fill this inbox</h2>
        <ConnectGmailButton className="mt-4" />
      </div>
    );
  }

  if (state.phase === "auth") {
    return (
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <h2 className="text-base font-medium text-strong">Your Gmail session needs a refresh</h2>
        <p className="mt-1.5 text-sm text-muted">
          The connection expired or was revoked. Reconnect Gmail to keep scanning your mail.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <ConnectGmailButton />
          <Link
            href="/login?redirect=/inbox"
            className="text-xs text-dim underline-offset-4 hover:text-strong hover:underline"
          >
            or sign in again →
          </Link>
        </div>
      </div>
    );
  }

  return (
    // GEOMETRY (#197): the locked-page arrangement, same terms as the filed
    // ledger. The two control plates — scan parameters, then category chips +
    // search — hold still at `lg`+, and everything the mine PRODUCES (failed
    // mine, file bar, follow-ups, verdicts) scrolls in one pane beneath them.
    // `lg:min-h-0` on this root and on the pane are both load-bearing: one
    // missing link re-inflates the flex column's content minimum and hands
    // the scroll back to <main> with nothing going red (geometry.ts).
    <div className="flex flex-col gap-6 lg:min-h-0 lg:flex-1">
      {/* --- Filter bar --------------------------------------------------- */}
      <div className="rounded-xl border border-line-soft bg-surface p-4 lg:shrink-0">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <label className="flex flex-col gap-1.5">
            <span className="label-caps">age</span>
            <Segmented<RangeValue>
              ariaLabel="Time range"
              options={RANGE_OPTIONS}
              value={filters.range}
              onChange={(range) => setFilters((f) => ({ ...f, range }))}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="label-caps">where</span>
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
            <span className="label-caps">fetch</span>
            <select
              aria-label="Number of messages to fetch"
              className={cn(selectClass, "w-28 py-1.5 text-xs")}
              value={filters.count}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  count: Number(e.target.value) as FetchCount,
                }))
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
            <div className="flex items-center justify-between text-xs text-dim">
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                mining {filters.scope === "anywhere" ? "all mail" : "inbox"}
                {filters.range !== "all" ? ` · last ${filters.range} mo` : ""}
              </span>
              <span className="tabular font-mono text-[11px]">
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
          <p className="tabular mt-3 text-xs text-dim">
            {email ? `${email} · ` : ""}
            {state.fetched.toLocaleString()} scanned · {jobRelatedTotal.toLocaleString()}{" "}
            job-related
          </p>
        )}
      </div>

      {/* --- Category summary + view filters ------------------------------
          Above the results pane, not inside it (#197): these narrow the list
          they sit over, so they hold still with the scan controls while the
          verdicts scroll. */}
      <div className="rounded-xl border border-line-soft bg-surface p-4 lg:shrink-0">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            aria-pressed={activeCategory === null}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              activeCategory === null
                ? "border-line-strong text-strong"
                : "border-line-soft text-dim hover:text-muted",
            )}
          >
            all {chipTotal(summary).toLocaleString()}
          </button>
          {/* One vocabulary with the filed ledger (`categoryChips`), not a
              second list that drifts: every category the counts name is
              offered, including one this build has never heard of. */}
          {categoryChips(summary).map((chip) => {
            const active = activeCategory === chip.value;
            return (
              <button
                key={chip.value}
                type="button"
                onClick={() => setActiveCategory(active ? null : chip.value)}
                aria-pressed={active}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  active
                    ? "border-line-strong text-strong"
                    : "border-line-soft text-muted hover:text-strong",
                )}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${chip.dot}`} aria-hidden />
                {chip.label} {chip.count}
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
          <label className="inline-flex cursor-pointer select-none items-center gap-2 text-xs text-muted">
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

      {/* --- The results pane: the ONE scroller at `lg`+ ------------------ */}
      <div data-testid="scan-results-pane" className="space-y-6 lg:min-h-0 lg:overflow-y-auto">
        {/* --- A failed mine, led with --------------------------------------
          The failure used to be a small dim line at the very BOTTOM of the
          page, under a success-shaped empty box reading "No messages matched
          this range" — a completed-scan verdict about a mailbox we never
          finished reading. It now leads the results pane, directly under the
          fixed control plates, and the empty box does not render at all when
          nothing was read. */}
        {mineFailed ? (
          <div role="alert" className="rounded-xl border border-reject/40 bg-surface p-6">
            <p className="label-caps text-reject-ink">scan failed</p>
            <h2 className="mt-2 text-base font-medium text-strong">
              We couldn&apos;t finish reading your mail.
            </h2>
            <p className="mt-1.5 text-sm text-muted">
              {state.fetched > 0
                ? `The scan stopped after ${state.fetched.toLocaleString()} of ${state.target.toLocaleString()} messages, so what's below is partial — not a picture of your whole mailbox.`
                : "Nothing was read, so nothing here says anything about what your mailbox holds."}{" "}
              Press Refresh to try again.
            </p>
            {state.errorStatus ? (
              <p className="tabular mt-1 font-mono text-[11px] text-dim">
                mail backend responded {state.errorStatus}
              </p>
            ) : null}
          </div>
        ) : null}

        {/* --- File the mine into the pipeline ------------------------------ */}
        {state.phase === "ready" && jobRelatedTotal > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line-soft bg-surface px-4 py-3">
            <div className="min-w-0">
              <p className="tabular text-xs text-muted">
                <span className="text-strong">{jobRelatedTotal.toLocaleString()}</span> job-related
                of {verdicts.length.toLocaleString()} scanned
              </p>
              {filing.note ? (
                <p
                  role="status"
                  className={cn(
                    "mt-1 text-xs",
                    filing.phase === "error" ? "text-reject-ink" : "text-dim",
                  )}
                >
                  {filing.note}
                  {filing.phase === "done" ? (
                    <>
                      {" · "}
                      <Link
                        href="/dashboard"
                        className="underline-offset-4 hover:text-strong hover:underline"
                      >
                        view applications →
                      </Link>
                    </>
                  ) : null}
                </p>
              ) : (
                <p className="mt-1 text-xs text-dim">
                  filing adds these to your applications — nothing is removed, and filing twice is
                  harmless
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => void fileThese()}
              disabled={filing.phase === "filing"}
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-strong px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90 focus-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {filing.phase === "filing" ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  Filing…
                </>
              ) : filing.phase === "done" ? (
                "File again"
              ) : (
                `File ${jobRelatedTotal.toLocaleString()} into Applications`
              )}
            </button>
          </div>
        ) : null}

        {/* --- Needs follow-up (ghosting) -----------------------------------
          A missing answer is not an empty one. When the analysis call fails
          this panel used to simply not render, and "no ghosting panel" reads
          as "nobody has ghosted you" — a claim only the analysis can make. */}
        {analysisFailed ? (
          <div role="status" className="rounded-xl border border-line-soft bg-surface p-5">
            <h2 className="flex items-center gap-2 text-base font-medium text-strong">
              <Bell className="h-4 w-4 text-dim" aria-hidden />
              Needs follow-up — unavailable
            </h2>
            <p className="mt-1 text-sm text-muted">
              The follow-up analysis didn&apos;t answer for this mine, so we can&apos;t say who has
              gone silent on you. This is a missing answer, not an empty one — the messages below
              are unaffected, and Refresh runs it again.
            </p>
          </div>
        ) : followUps.length > 0 ? (
          <div className="rounded-xl border border-review/40 bg-surface p-5">
            <h2 className="flex items-center gap-2 text-base font-medium text-strong">
              <Bell className="h-4 w-4 text-review" aria-hidden />
              Needs follow-up ({followUps.length})
            </h2>
            <p className="mt-1 text-sm text-muted">
              You applied but never heard back — no interview, assessment, offer, or rejection
              since.
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

        {/* --- Verdict list ------------------------------------------------- */}
        {loading && verdicts.length === 0 ? (
          <ul className="rounded-xl border border-line-soft bg-surface px-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonRow key={i} />
            ))}
          </ul>
        ) : filtered.length > 0 ? (
          <ul className="rounded-xl border border-line-soft bg-surface px-3">
            {filtered.map((v) => (
              <VerdictRow
                key={v.message_id}
                v={v}
                classify={transport.classify}
                onCorrected={applyCorrection}
              />
            ))}
          </ul>
        ) : mineFailed && verdicts.length === 0 ? null : (
          <div className="rounded-xl border border-dashed border-line-soft bg-surface p-8 text-center text-sm text-muted">
            {verdicts.length === 0
              ? "No messages matched this range. Widen the age window or switch to All mail."
              : "No messages match these view filters."}
          </div>
        )}
      </div>
    </div>
  );
}
