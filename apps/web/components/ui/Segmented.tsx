"use client";

import { cn } from "@/lib/utils";

/**
 * The segmented control the inbox workbench introduced (age / where), extracted
 * so the rebuild dialog can reuse it verbatim — deliberate visual continuity:
 * the user who learned these controls on `/inbox` meets the same ones in the
 * dashboard's rebuild dialog.
 */
export function Segmented<T extends string>({
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
