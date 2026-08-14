"use client";

/**
 * The settings pages' switch — lived inside `NotificationsSection` until the
 * Appearance card grew a toggle of its own (the ambient-mail switch); shared
 * so the two cards cannot drift into two switch designs.
 */
export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm text-strong">{label}</p>
        <p className="mt-0.5 text-[12px] leading-snug text-muted">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong ${
          checked ? "border-live/60 bg-live/25" : "border-line bg-surface-2"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all ${
            checked ? "left-[18px] bg-live" : "left-0.5 bg-dim"
          }`}
          aria-hidden="true"
        />
      </button>
    </div>
  );
}
