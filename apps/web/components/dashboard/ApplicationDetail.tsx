"use client";

import { ExternalLink, Loader2, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { AUTO_FILE_GATE, GateMeter } from "@/components/viz/GateMeter";
import { filedAt, longDate, shortDate } from "@/lib/dashboard/dates";
import {
  readApplicationDetail,
  type ApplicationDetail as DetailData,
  type SplitCandidate,
} from "@/lib/dashboard/detail";
import { statusChangeFailure } from "@/lib/dashboard/rowActions";
import { statusOptions, statusSelectValue } from "@/lib/dashboard/status";
import { STAGES, stageOf, type Application } from "@/lib/dashboard/summary";
import { liveBoardTransport, type BoardTransport } from "@/lib/dashboard/transport";
import { CATEGORY_META } from "@/lib/gmail/types";

/**
 * The application detail sheet — the mail behind a card.
 *
 * `GET /api/applications/{id}` existed and was called by nothing: there was no
 * way to open a card and see which of four Amazon roles it is, or the thread
 * of verdicts that filed and advanced it. This sheet is that view, and it is
 * the product's identity moment inside the app: each message renders as one
 * step of a verdict trail — category dot, confidence, subject, sender, date —
 * the same vocabulary as the landing's decision trace, because it is the same
 * fact ("your inbox already holds the verdict") shown on the user's own row.
 *
 * The stage control here is real (same PATCH + optimistic/rollback contract as
 * the card), not a display; every Gmail link opens the actual conversation.
 */

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; detail: DetailData };

function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

function TrailMessage({ message, isLast }: { message: DetailData["messages"][number]; isLast: boolean }) {
  const meta = message.category
    ? (CATEGORY_META[message.category] ?? { label: message.category, dot: "bg-dim" })
    : null;
  const sender = message.sender_name || message.sender_email || "unknown sender";
  return (
    <li className="relative pl-6">
      {/* The trail: a hairline spine with one category-hued node per message. */}
      {!isLast ? (
        <span aria-hidden className="absolute left-[3px] top-4 h-full w-px bg-line-soft" />
      ) : null}
      <span
        aria-hidden
        className={`absolute left-0 top-1.5 h-[7px] w-[7px] rounded-full ${meta?.dot ?? "bg-dim"}`}
      />
      <div className="flex items-baseline justify-between gap-3">
        <p className="min-w-0 truncate text-sm font-medium text-strong">
          {message.subject || "(no subject)"}
        </p>
        <span className="tabular shrink-0 font-mono text-[10px] text-dim">
          {message.received_at ? shortDate(message.received_at) : ""}
        </span>
      </div>
      <p className="truncate text-xs text-muted">{sender}</p>
      {meta ? (
        // The verdict, in the DecisionTrace's vocabulary: category, then the
        // confidence drawn against the 0.85 gate — green cleared it, amber
        // waited for a human. The number stays as the accessible value.
        <p className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-dim">
          {meta.label}
          {typeof message.confidence === "number" ? (
            <>
              <GateMeter confidence={message.confidence} className="w-12" />
              <span
                className="tabular"
                style={{
                  color:
                    message.confidence >= AUTO_FILE_GATE ? "var(--green)" : "var(--amber)",
                }}
              >
                {pct(message.confidence)}
              </span>
            </>
          ) : null}
        </p>
      ) : null}
      {message.snippet ? (
        <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-dim">{message.snippet}</p>
      ) : null}
      {message.gmail_link ? (
        <a
          href={message.gmail_link}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1 font-mono text-[10px] text-dim underline-offset-2 hover:text-strong hover:underline"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          open in gmail
        </a>
      ) : null}
    </li>
  );
}

/**
 * "This looks like N applications — split?" for a merged row.
 *
 * TODO(backend): renders ONLY when the detail response carries
 * `split_candidates` (see `lib/dashboard/detail.ts`) and posts to
 * `POST /api/applications/{id}/split` — neither exists until the entity-model
 * branch lands, so today this component never mounts and no decorative
 * control ships. The wiring is here so the surface lights up the moment the
 * backend starts sending candidates.
 */
function SplitPrompt({
  applicationId,
  company,
  candidates,
  onSplit,
}: {
  applicationId: number;
  company: string;
  candidates: SplitCandidate[];
  onSplit: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (candidates.length < 2) return null;

  async function split() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/applications/${applicationId}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidates }),
      });
      if (!res.ok) {
        setError("Couldn't split this row — it is unchanged.");
        setBusy(false);
        return;
      }
      onSplit();
    } catch {
      setError("Couldn't split this row — it is unchanged.");
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-review/40 bg-surface-2 p-3">
      <p className="text-sm text-strong">
        This looks like {candidates.length} applications at {company} — split them?
      </p>
      <ul className="mt-2 space-y-1">
        {candidates.map((c) => (
          <li key={c.position} className="font-mono text-[11px] text-muted">
            {company} · {c.position}
          </li>
        ))}
      </ul>
      <p className="mt-2 font-mono text-[10px] text-dim">
        each becomes its own card · your edits stay on this one
      </p>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void split()}
          disabled={busy}
          className="rounded border border-review/50 px-2 py-1 font-mono text-[11px] text-strong transition-colors hover:border-review disabled:opacity-50"
        >
          {busy ? "splitting…" : `Split into ${candidates.length}`}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 font-mono text-[10px] text-reject">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function ApplicationDetail({
  app,
  onClose,
  transport = liveBoardTransport,
}: {
  /** The card being inspected; `null` keeps the sheet closed. */
  app: Application | null;
  onClose: () => void;
  /** How reads/mutations reach data — the live proxy by default, fixtures on /demo. */
  transport?: BoardTransport;
}) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [stageBusy, setStageBusy] = useState(false);
  const [stageError, setStageError] = useState<string | null>(null);
  /** The stage the user just picked here, shown before the server confirms. */
  const [optimistic, setOptimistic] = useState<string | null>(null);

  const load = useCallback(
    async (id: number) => {
      setState({ kind: "loading" });
      const res = await transport.detail(id);
      if (!res.ok) {
        setState({ kind: "error" });
        return;
      }
      setState({ kind: "ready", detail: readApplicationDetail(res.body) });
    },
    [transport],
  );

  useEffect(() => {
    if (!app) return;
    // Deferred off the effect body (the house rule — see BetaBanner): the
    // reset + fetch kick off in a macrotask, never a synchronous setState.
    const id = window.setTimeout(() => {
      setOptimistic(null);
      setStageError(null);
      void load(app.id);
    }, 0);
    return () => window.clearTimeout(id);
  }, [app, load]);

  // The card last inspected, retained through close: the Dialog's exit
  // animation plays over real content instead of a blank panel (guarded
  // render-adjustment — the same pattern the board's optimistic overlay uses).
  const [shown, setShown] = useState<Application | null>(app);
  if (app && app !== shown) setShown(app);

  if (!shown) return null;
  const active = shown;

  const shownStatus = optimistic ?? active.status;
  const stage = STAGES.find((s) => s.key === stageOf(shownStatus))!;
  const role = active.position.trim();

  async function onStageChange(next: string) {
    if (next === shownStatus) return;
    setStageError(null);
    setOptimistic(next);
    setStageBusy(true);
    const result = await transport.changeStatus(active.id, next);
    setStageBusy(false);
    if (!result.ok) {
      setOptimistic(null);
      setStageError(statusChangeFailure(next, active.status, result.detail));
      return;
    }
    router.refresh();
  }

  return (
    <Dialog
      open={app !== null}
      onClose={onClose}
      variant="sheet"
      title={active.company}
      description={role || "role not captured yet"}
    >
      <div className="space-y-5">
        {/* --- The row's own facts + the working stage control ------------- */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor={`detail-status-${active.id}`}>
              Change stage for {active.company}
            </label>
            <select
              id={`detail-status-${active.id}`}
              value={statusSelectValue(shownStatus)}
              disabled={stageBusy}
              onChange={(e) => void onStageChange(e.target.value)}
              className="rounded border border-line bg-surface-2 px-2 py-1 font-mono text-[11px] outline-none transition-colors hover:border-line-strong focus:border-line-strong disabled:opacity-50"
              style={{ color: stage.color }}
            >
              {statusOptions(shownStatus).map((option) => (
                <option key={option.value} value={option.value} disabled={option.disabled}>
                  {option.label}
                </option>
              ))}
            </select>
            {stageBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-dim motion-reduce:animate-none" aria-hidden />
            ) : null}
          </div>
          <span className="tabular font-mono text-[11px] text-dim">filed {longDate(filedAt(active))}</span>
          {active.url ? (
            <a
              href={active.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-mono text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              open in gmail
            </a>
          ) : null}
        </div>

        {stageError ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 rounded border border-reject/50 bg-reject/10 px-2 py-1.5 text-xs leading-snug text-strong"
          >
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject" aria-hidden />
            <span>{stageError}</span>
          </p>
        ) : null}

        {active.notes ? (
          <p className="rounded-lg border border-line-soft bg-surface-2 p-3 text-[12px] leading-relaxed text-muted">
            {active.notes}
          </p>
        ) : null}

        {/* --- The verdict trail ------------------------------------------- */}
        <div>
          <p className="label-mono mb-3">the mail behind this card</p>
          {state.kind === "loading" ? (
            <p className="flex items-center gap-2 font-mono text-[11px] text-dim" role="status">
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
              loading the mail trail…
            </p>
          ) : state.kind === "error" ? (
            <div role="alert" className="rounded-lg border border-reject/40 bg-surface-2 p-3">
              <p className="text-xs text-strong">Couldn&apos;t load the mail behind this card.</p>
              <button
                type="button"
                onClick={() => void load(active.id)}
                className="mt-2 rounded border border-line px-2 py-1 font-mono text-[11px] text-foreground transition-colors hover:border-line-strong hover:text-strong"
              >
                try again
              </button>
            </div>
          ) : state.detail.messages.length === 0 ? (
            <p className="font-mono text-[11px] text-dim">
              no linked mail — this row was filed by hand
            </p>
          ) : (
            <ul className="space-y-4">
              {state.detail.messages.map((message, i) => (
                <TrailMessage
                  key={message.message_id}
                  message={message}
                  isLast={i === state.detail.messages.length - 1}
                />
              ))}
            </ul>
          )}
        </div>

        {state.kind === "ready" ? (
          <SplitPrompt
            applicationId={active.id}
            company={active.company}
            candidates={state.detail.splitCandidates}
            onSplit={() => {
              onClose();
              router.refresh();
            }}
          />
        ) : null}

        {active.source ? (
          <p className="border-t border-line-soft pt-3 font-mono text-[10px] text-dim">
            source · {active.source === "gmail" ? "filed automatically from gmail" : active.source}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
