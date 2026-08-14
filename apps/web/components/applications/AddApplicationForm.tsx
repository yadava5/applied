"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { Plus } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { Dialog } from "@/components/ui/Dialog";
import {
  fieldLabelClass,
  inputClass,
  primaryBtnClass,
  secondaryBtnClass,
  selectClass,
  textareaClass,
} from "@/components/ui/formStyles";
import { APPLICATION_STATUSES } from "@/lib/dashboard/status";

/**
 * The stage vocabulary, imported rather than restated.
 *
 * This dialog held the last hand-written copy: six values, missing `ghosted`
 * (which the API accepts) — one of the three lists that disagreed when setting
 * a card to `assessment` answered 422. The card's `<select>` was fixed by
 * deleting its literal and importing this one; this one was left behind, so it
 * would have been the single place a filed-by-hand application could not be
 * filed as an assessment.
 */
const STATUS_OPTIONS = APPLICATION_STATUSES;

type Mode = "live" | "demo";

/** How long the "Filed …" receipt stays on screen. */
const CONFIRMATION_MS = 8000;

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    // `new URL` is lenient (it will happily accept "https://not a url"), so
    // require an http(s) scheme and a dotted hostname — enough to catch typos
    // without rejecting a real job link.
    return (url.protocol === "http:" || url.protocol === "https:") && url.hostname.includes(".");
  } catch {
    return false;
  }
}

/**
 * File an application. A trigger button opens a clean, focus-trapped modal —
 * no inline slide-down, no dead space, no layout shift on the page behind it.
 * On the live dashboard the form posts through the server-side proxy
 * (`/api/applications`, which carries the Supabase JWT) and refreshes the board;
 * in `demo` mode it validates and confirms without a network call so the exact
 * same UX is exercisable on the public `/demo`.
 */
export function AddApplicationForm({
  mode = "live",
  align = "end",
  compact = false,
}: {
  mode?: Mode;
  align?: "start" | "end";
  /** Render an unobtrusive "+" icon instead of the prominent labelled button.
   *  Manual filing is now the rare path — the pipeline fills from Gmail. */
  compact?: boolean;
}) {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const companyId = useId();
  const positionId = useId();
  const statusId = useId();
  const dateId = useId();
  const linkId = useId();
  const notesId = useId();

  /**
   * The confirmation is a receipt, not a status: it says what just happened
   * and then gets out of the way. It used to be set and never cleared, so
   * "Filed 'X' — role." sat under the `+` button for the life of the mount,
   * outliving the filing it described and (after a `router.refresh()`) the
   * board state it was about. It clears on a timer, and again when the form is
   * reopened — nobody should be reading a stale receipt while filing the next
   * one. Ample margin over any assertion that reads it right after a submit.
   */
  useEffect(() => {
    if (confirmation === null) return;
    const id = window.setTimeout(() => setConfirmation(null), CONFIRMATION_MS);
    return () => window.clearTimeout(id);
  }, [confirmation]);

  function openForm() {
    setConfirmation(null);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setError(null);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const form = new FormData(e.currentTarget);
    const company = String(form.get("company") ?? "").trim();
    const position = String(form.get("position") ?? "").trim();
    const status = String(form.get("status") ?? "applied");
    const applied = String(form.get("applied") ?? "").trim();
    const linkRaw = String(form.get("link") ?? "").trim();
    const notes = String(form.get("notes") ?? "");

    if (!company || !position) {
      setError("Company and role are both required.");
      return;
    }

    const link = normalizeUrl(linkRaw);
    if (link && !isValidUrl(link)) {
      setError("The link doesn't look like a valid URL.");
      return;
    }

    const trimmedNotes = notes.trim();

    if (mode === "demo") {
      setConfirmation(`Filed “${company}” — demo only, not saved.`);
      close();
      return;
    }

    setBusy(true);
    // `applied_date` and `url` are real columns now, so they are sent as
    // themselves. They used to be stringified into `notes` because the create
    // model had no fields for them — which meant a hand-filed application
    // landed with a null date and a link that was never a link, while every
    // Gmail-sourced row had both. `applied_date` takes YYYY-MM-DD, exactly
    // what a native date input produces.
    const res = await fetch("/api/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company,
        position,
        status,
        applied_date: applied || undefined,
        url: link || undefined,
        notes: trimmedNotes || undefined,
      }),
    });
    setBusy(false);

    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      setError(typeof body.detail === "string" ? body.detail : "The backend refused the filing.");
      return;
    }

    close();
    setConfirmation(`Filed “${company}” — ${position}.`);
    router.refresh();
  }

  return (
    // `relative` parents BOTH states of the receipt below: the overlay plate
    // anchors to this box, and the silent `sr-only` frame resolves against it
    // rather than the initial containing block (Tailwind's `.sr-only` is
    // `position: absolute` — unparented it plants a box at document scale,
    // the same shape that once made the whole shell scroll, #149).
    <div className={`relative flex flex-col ${align === "end" ? "items-end" : "items-start"}`}>
      {compact ? (
        <button
          type="button"
          onClick={openForm}
          title="File an application by hand"
          aria-label="File an application by hand"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-dim transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      ) : (
        <button type="button" onClick={openForm} className={primaryBtnClass}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          File an application
        </button>
      )}

      {/* The filing receipt — persistent and out of flow, both by contract
          (#81). Persistent: a live region mounted on demand drops its first
          announcement, so a screen-reader user was never told their filing
          happened; this <p> is in the DOM from the first render and `role=
          "status"` announces whatever lands in it. Out of flow: the in-flow
          line used to push everything below the button down ~13px on /demo —
          and on the dashboard this component sits INSIDE the header row whose
          zero-shift contract SyncBar defends (#160) — so when it speaks it is
          an anchored plate over the content below, costing no height
          anywhere. `data-filing-receipt` names it for the spec that asserts
          both halves (file-application.spec.ts). */}
      <p
        role="status"
        aria-live="polite"
        data-filing-receipt=""
        title={confirmation ?? undefined}
        // Below `sm` the anchored form clips: the compact `+` sits mid-row on
        // the stacked cluster line, and a right-anchored 274px plate ran 90px
        // off the left screen edge at 375 (measured — the receipt read
        // "…d Labs" — demo only, not saved."). Down there it is a fixed
        // snackbar instead: the one anchor a phone always has is the
        // viewport, and fixed takes no flow space either.
        className={
          confirmation === null
            ? "sr-only"
            : `absolute top-full z-30 mt-1.5 max-w-[min(20rem,80vw)] whitespace-nowrap rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-live shadow-md max-sm:fixed max-sm:inset-x-3 max-sm:bottom-4 max-sm:top-auto max-sm:mt-0 max-sm:max-w-none ${
                align === "end" ? "right-0" : "left-0"
              }`
        }
      >
        {confirmation ? (
          // The fade-rise every arriving surface here wears (0.18s, static
          // under reduced motion): out of flow, nothing moves to mark the
          // receipt's arrival, so the entrance is what draws the eye.
          <motion.span
            key={confirmation}
            initial={reduceMotion ? false : { opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="block truncate"
          >
            {confirmation}
          </motion.span>
        ) : null}
      </p>

      <Dialog
        open={open}
        onClose={close}
        title="File an application"
        description="For applications your mail doesn't know about. Only company and role are required."
      >
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2">
          <label htmlFor={companyId} className="grid gap-1">
            <span className={fieldLabelClass}>company *</span>
            <input id={companyId} name="company" required className={inputClass} />
          </label>
          <label htmlFor={positionId} className="grid gap-1">
            <span className={fieldLabelClass}>role *</span>
            <input id={positionId} name="position" required className={inputClass} />
          </label>
          <label htmlFor={statusId} className="grid gap-1">
            <span className={fieldLabelClass}>stage</span>
            <select id={statusId} name="status" defaultValue="applied" className={selectClass}>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={dateId} className="grid gap-1">
            <span className={fieldLabelClass}>applied date</span>
            <input id={dateId} name="applied" type="date" className={inputClass} />
          </label>
          <label htmlFor={linkId} className="grid gap-1 sm:col-span-2">
            <span className={fieldLabelClass}>link (job post / thread)</span>
            <input
              id={linkId}
              name="link"
              type="text"
              inputMode="url"
              placeholder="https://…"
              className={inputClass}
            />
          </label>
          <label htmlFor={notesId} className="grid gap-1 sm:col-span-2">
            <span className={fieldLabelClass}>notes</span>
            <textarea id={notesId} name="notes" className={textareaClass} />
          </label>

          {error ? (
            <p role="alert" className="text-xs text-reject-ink sm:col-span-2">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 sm:col-span-2">
            <button type="button" onClick={close} className={secondaryBtnClass}>
              Cancel
            </button>
            <button type="submit" disabled={busy} className={primaryBtnClass}>
              {busy ? "Filing…" : "File it"}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
