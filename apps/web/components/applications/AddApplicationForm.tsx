"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Plus } from "lucide-react";

import { Dialog } from "@/components/ui/Dialog";
import {
  fieldLabelClass,
  inputClass,
  primaryBtnClass,
  secondaryBtnClass,
  selectClass,
  textareaClass,
} from "@/components/ui/formStyles";

const STATUS_OPTIONS = [
  "applied",
  "interviewing",
  "offered",
  "rejected",
  "accepted",
  "withdrawn",
] as const;

type Mode = "live" | "demo";

/** Compose the optional applied-date + link into the notes the backend stores,
 * so no field the user filled in is silently dropped by the leaner API shape. */
function composeNotes(notes: string, applied: string, link: string): string | null {
  const meta = [applied ? `applied ${applied}` : "", link ? link : ""].filter(Boolean).join(" · ");
  const composed = [meta, notes.trim()].filter(Boolean).join(" — ");
  return composed || null;
}

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
}: {
  mode?: Mode;
  align?: "start" | "end";
}) {
  const router = useRouter();
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

    const composedNotes = composeNotes(notes, applied, link);

    if (mode === "demo") {
      setConfirmation(`Filed “${company}” — demo only, not saved.`);
      close();
      return;
    }

    setBusy(true);
    const res = await fetch("/api/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company, position, status, notes: composedNotes ?? undefined }),
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
    <div className={`flex flex-col gap-1.5 ${align === "end" ? "items-end" : "items-start"}`}>
      <button type="button" onClick={() => setOpen(true)} className={primaryBtnClass}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        File an application
      </button>

      {confirmation ? (
        <p role="status" className="font-mono text-[11px] text-live">
          {confirmation}
        </p>
      ) : null}

      <Dialog
        open={open}
        onClose={close}
        title="File an application"
        description="Add a role to your pipeline. Only company and role are required."
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
            <p role="alert" className="font-mono text-xs text-reject sm:col-span-2">
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
