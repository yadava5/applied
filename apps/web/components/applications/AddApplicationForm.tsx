"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Minimal filing form. Posts to the server-side proxy (/api/applications)
 * so no backend URL or token ever reaches the browser, then refreshes the
 * RSC tree so the board re-renders with the new row.
 */
export function AddApplicationForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const res = await fetch("/api/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company: form.get("company"),
        position: form.get("position"),
        status: form.get("status") || "applied",
        notes: form.get("notes") || undefined,
      }),
    });
    setBusy(false);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "The backend refused the filing.");
      return;
    }
    (e.target as HTMLFormElement).reset?.();
    setOpen(false);
    router.refresh();
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-lg border border-line px-4 py-2 font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:border-line-strong hover:text-strong"
      >
        + file an application
      </button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="grid gap-3 rounded-xl border border-line-soft bg-surface p-4 sm:grid-cols-2"
    >
      <label className="grid gap-1">
        <span className="label-mono">company</span>
        <input
          name="company"
          required
          className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none focus:border-line-strong"
        />
      </label>
      <label className="grid gap-1">
        <span className="label-mono">position</span>
        <input
          name="position"
          required
          className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none focus:border-line-strong"
        />
      </label>
      <label className="grid gap-1">
        <span className="label-mono">status</span>
        <select
          name="status"
          defaultValue="applied"
          className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none focus:border-line-strong"
        >
          {["applied", "interviewing", "offered", "rejected", "accepted", "withdrawn"].map(
            (s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ),
          )}
        </select>
      </label>
      <label className="grid gap-1">
        <span className="label-mono">notes</span>
        <input
          name="notes"
          className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none focus:border-line-strong"
        />
      </label>
      {error && (
        <p role="alert" className="font-mono text-xs text-review sm:col-span-2">
          {error}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background disabled:opacity-40"
        >
          {busy ? "filing…" : "File it"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-lg border border-line px-4 py-2 text-sm text-muted"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
