import type { ReactNode } from "react";

/**
 * One Settings card: a consistent titled surface every section composes into,
 * so spacing, borders, and heading rhythm never drift between sections.
 */
export function SettingsSection({
  title,
  description,
  id,
  children,
  tone = "default",
}: {
  title: string;
  description?: ReactNode;
  id?: string;
  children: ReactNode;
  tone?: "default" | "danger";
}) {
  return (
    // `scroll-mt-16` below `lg` clears the chip strip SettingsNav pins to the
    // top of the scroll pane (53px tall) — without it an anchor jump lands the
    // heading underneath it. At `lg` the rail sits beside the cards with
    // nothing above them, so the jump only needs room to breathe.
    <section
      id={id}
      aria-label={title}
      className={`scroll-mt-16 rounded-xl border bg-surface p-5 lg:scroll-mt-4 ${
        tone === "danger" ? "border-reject/30" : "border-line-soft"
      }`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-medium text-strong">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** A labelled read-only value row (email, member-since, sign-in method). */
export function ReadonlyField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid gap-1">
      <span className="label-caps">{label}</span>
      <span className="text-sm text-muted">{value}</span>
    </div>
  );
}

/** A tiny inline save-status line shared by the client sections. */
export function SaveStatus({ state }: { state: "idle" | "saving" | "saved" | "error"; }) {
  if (state === "idle") return null;
  const map = {
    saving: { text: "Saving…", cls: "text-dim" },
    saved: { text: "Saved", cls: "text-live" },
    error: { text: "Couldn’t save — try again.", cls: "text-reject-ink" },
  } as const;
  const { text, cls } = map[state];
  return (
    <span role="status" className={`text-xs ${cls}`}>
      {text}
    </span>
  );
}
