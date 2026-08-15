import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

/**
 * The quiet form's envelope — the Triage boot's glyph stilled into a
 * loading.tsx texture. Each row's envelope takes its turn under the rules
 * hue with a verdict-dot flash (`boot-quiet-*` in globals.css), so a pending
 * route reads as the classifier mid-pass rather than as blank theme-colored
 * blobs. `index` staggers the row along the shared cadence; under
 * prefers-reduced-motion everything freezes and only the `lit` row keeps its
 * verdict as a still poster.
 */
export function QuietEnvelope({
  index,
  lit = false,
  className,
}: {
  index: number;
  lit?: boolean;
  className?: string;
}) {
  return (
    <span
      // `inline-block`, not the default `inline`: a bare <span> ignores width
      // and height, so outside a flex row (where it would be blockified) the
      // sizing className silently did nothing and the svg grew to the line's
      // full width. Flex parents blockify it anyway, so this costs the
      // existing call sites nothing.
      className={cn("boot-quiet-env inline-block shrink-0", className)}
      style={{ "--i": index } as CSSProperties}
      data-lit={lit || undefined}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 17" className="block h-full w-full">
        <rect
          x="0.8"
          y="0.8"
          width="22.4"
          height="15.4"
          rx="2.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        />
        <path
          d="M0.8,0.8 L12,9 L23.2,0.8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        />
        <circle
          className="boot-quiet-dot"
          cx="12"
          cy="8.5"
          r="2.2"
          fill="currentColor"
          stroke="none"
        />
      </svg>
    </span>
  );
}
