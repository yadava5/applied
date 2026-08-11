"use client";

import { ExternalLink, Loader2, MoreHorizontal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { filedAt, shortDate } from "@/lib/dashboard/dates";
import { type Application, STAGES, qualifierOf, stageOf } from "@/lib/dashboard/summary";

/** The statuses a user can set from the board (a superset of the four stages). */
const STATUS_CHOICES = [
  "applied",
  "interviewing",
  "assessment",
  "offered",
  "accepted",
  "rejected",
  "withdrawn",
] as const;

/**
 * One pipeline row — now clickable + correctable.
 *
 * - "Open in Gmail" deep-links to the underlying conversation (metadata is all
 *   we hold; the real mail lives in Gmail).
 * - The stage <select> applies a status CORRECTION: the backend makes it sticky
 *   (a future sync never overwrites it) AND records a training example.
 * - The menu offers "Not an application" (dismiss + train "other") and delete.
 *
 * Every mutation posts to a same-origin proxy (JWT stays server-side) and, on
 * success, `router.refresh()` re-renders the server board from fresh data.
 */
export function ApplicationCard({ app }: { app: Application }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const qualifier = qualifierOf(app.status);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  // Real received date from the mail; fall back to the row's filed date.
  const filed = filedAt(app);
  const fromGmail = app.source === "gmail" || app.source === "gmail_user";

  async function mutate(run: () => Promise<Response>, failMsg: string) {
    setBusy(true);
    setError(null);
    setMenuOpen(false);
    try {
      const res = await run();
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        setError(typeof body.detail === "string" ? body.detail : failMsg);
        setBusy(false);
        return;
      }
      router.refresh();
      // Leave `busy` on until the refresh swaps this subtree out.
    } catch {
      setError(failMsg);
      setBusy(false);
    }
  }

  function onStatusChange(next: string) {
    if (next === app.status) return;
    void mutate(
      () =>
        fetch(`/api/applications/${app.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: next }),
        }),
      "Couldn't update the status.",
    );
  }

  function onDismiss() {
    void mutate(
      () => fetch(`/api/applications/${app.id}/dismiss`, { method: "POST" }),
      "Couldn't dismiss this row.",
    );
  }

  function onDelete() {
    void mutate(
      () => fetch(`/api/applications/${app.id}`, { method: "DELETE" }),
      "Couldn't delete this row.",
    );
  }

  return (
    <li
      className="group/card relative rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
      style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-strong">
          <span className="truncate">{app.company}</span>
          {qualifier && (
            <span className="shrink-0 rounded-full border border-line px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-muted">
              {qualifier}
            </span>
          )}
        </p>
        <div className="flex shrink-0 items-center gap-1">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-dim" aria-hidden />}
          <button
            type="button"
            aria-label="Row actions"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="rounded p-0.5 text-dim opacity-0 transition-opacity hover:text-strong focus-visible:opacity-100 group-hover/card:opacity-100"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </div>

      {app.position ? <p className="truncate text-xs text-muted">{app.position}</p> : null}

      <div className="mt-2 flex items-center justify-between gap-2">
        <label className="sr-only" htmlFor={`status-${app.id}`}>
          Change stage for {app.company}
        </label>
        <select
          id={`status-${app.id}`}
          value={STATUS_CHOICES.includes(app.status as (typeof STATUS_CHOICES)[number]) ? app.status : "applied"}
          disabled={busy}
          onChange={(e) => onStatusChange(e.target.value)}
          className="max-w-[8.5rem] rounded border border-line-soft bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
        >
          {STATUS_CHOICES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="tabular font-mono text-[10px] text-dim">{shortDate(filed)}</span>
      </div>

      {app.url ? (
        <a
          href={app.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 font-mono text-[10px] text-dim underline-offset-2 hover:text-strong hover:underline"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          open in gmail
        </a>
      ) : null}

      {error ? (
        <p role="alert" className="mt-1.5 font-mono text-[10px] text-reject">
          {error}
        </p>
      ) : null}

      {menuOpen ? (
        <div
          className="absolute right-2 top-8 z-10 w-40 overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            onClick={onDismiss}
            disabled={busy}
            className="block w-full px-3 py-2 text-left text-xs text-muted transition-colors hover:bg-surface-2 hover:text-strong disabled:opacity-50"
          >
            Not an application
            {fromGmail ? <span className="block font-mono text-[9px] text-dim">removes + trains model</span> : null}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={onDelete}
            disabled={busy}
            className="block w-full border-t border-line-soft px-3 py-2 text-left text-xs text-reject transition-colors hover:bg-reject/10 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      ) : null}
    </li>
  );
}
