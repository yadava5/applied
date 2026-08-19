import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

/**
 * Applied — the product wordmark and mark. Concept A: an ascending pipeline
 * tile (applied → interview → offer) next to the lowercase "applied" wordmark,
 * closed by an emerald verdict node ("your inbox already holds the verdict").
 *
 * Theme-aware by construction: the wordmark rides `currentColor`, so it inherits
 * whatever text color the surface uses and re-themes for free in light + dark.
 * The pipeline accents reuse the app's data-viz tokens — cyan = rules process,
 * emerald = SetFit verdict — so the logo speaks the same palette as the rest of
 * the UI rather than introducing its own. The tile stays a fixed dark badge in
 * both themes (an app-icon convention) with a hairline border.
 *
 * Micro-interaction: wrap the logo in a `.brand-logo-link` (any interactive
 * ancestor — every call site is a Link). On hover / keyboard-focus the pipeline
 * "runs" — each node pings in sequence up to the verdict — echoing the landing
 * `sig-pulse` choreography and the `beta-dot` ping, and the lockup lifts on the
 * same spring curve the app's buttons use. All of it collapses to a static logo
 * under `prefers-reduced-motion` (see globals.css).
 *
 * Entrance: inside an `.auth-hero` (the auth pages' front door,
 * components/auth/AuthHeader.tsx) the lockup ASSEMBLES once on arrival — the
 * closing act's stroke-draw device (`pathLength={1}`, dashoffset 1 → 0)
 * applied to the brand asset itself rather than a copy. The hooks here are
 * inert everywhere else: `--dw` is each element's ABSOLUTE delay into that
 * sequence (never chained — an inner relative delay is how an animated SVG
 * quietly de-syncs), and `pathLength` changes nothing until a dash is set.
 * The composed lockup is the base state in CSS, so reduced motion and every
 * non-auth mount render it finished (globals.css, "Auth front door").
 */

type LogoProps = {
  /** "full" = tile + wordmark lockup; "mark" = the pipeline tile alone. */
  variant?: "full" | "mark";
  className?: string;
  /** Accessible name for the standalone graphic. */
  title?: string;
};

const node = (d: string, dw: string): CSSProperties => ({
  ["--d" as string]: d,
  ["--dw" as string]: dw,
});
/** Absolute entrance delay for a drawn / faded element (`.auth-hero` only). */
const draw = (dw: string): CSSProperties => ({ ["--dw" as string]: dw });

/** The pipeline tile: two cyan process rings ascending to an emerald verdict. */
function Mark() {
  return (
    <>
      <rect
        className="brand-logo__tile"
        x="0.75"
        y="0.75"
        width="46.5"
        height="46.5"
        rx="12"
        fill="#0A0A0B"
        stroke="rgba(128,128,128,0.4)"
        strokeWidth="1.5"
      />
      <g strokeLinecap="round">
        <path
          className="brand-logo__edge"
          style={draw("0.18s")}
          d="M17.2,30.2 L20.3,27.4"
          stroke="#F7F8F8"
          strokeOpacity="0.65"
          strokeWidth="2"
        />
        <path
          className="brand-logo__edge"
          style={draw("0.34s")}
          d="M27.7,20.7 L30.6,18.1"
          stroke="#F7F8F8"
          strokeOpacity="0.65"
          strokeWidth="2"
        />
        <circle
          className="brand-logo__node brand-logo__proc"
          style={node("0ms", "0.1s")}
          cx="13.5"
          cy="33.5"
          r="3"
          fill="none"
          strokeWidth="2.4"
        />
        <circle
          className="brand-logo__node brand-logo__proc"
          style={node("80ms", "0.26s")}
          cx="24"
          cy="24"
          r="3"
          fill="none"
          strokeWidth="2.4"
        />
        <circle
          className="brand-logo__node brand-logo__verdict"
          style={node("160ms", "0.44s")}
          cx="34.5"
          cy="14.5"
          r="4.1"
          stroke="none"
        />
      </g>
    </>
  );
}

/** The lowercase "applied" wordmark, drawn in `currentColor`. */
function Wordmark() {
  return (
    <>
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="butt"
        strokeLinejoin="miter"
        transform="translate(0,10.5)"
      >
        <g
          className="brand-logo__stroke"
          style={draw("0.04s")}
          transform="translate(64,0)"
        >
          <path
            pathLength={1}
            d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5"
          />
          <path pathLength={1} d="M10.85,7 L10.85,20" />
        </g>
        <g
          className="brand-logo__stroke"
          style={draw("0.12s")}
          transform="translate(79,0)"
        >
          <path
            pathLength={1}
            d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5"
          />
          <path pathLength={1} d="M0.15,7 L0.15,26" />
        </g>
        <g
          className="brand-logo__stroke"
          style={draw("0.2s")}
          transform="translate(94,0)"
        >
          <path
            pathLength={1}
            d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5"
          />
          <path pathLength={1} d="M0.15,7 L0.15,26" />
        </g>
        <g
          className="brand-logo__stroke"
          style={draw("0.28s")}
          transform="translate(111.8,0)"
        >
          <path pathLength={1} d="M1.8,0 L1.8,16.4 A3.6,3.6 0 0 0 5.4,20" />
        </g>
        <g
          className="brand-logo__stroke"
          style={draw("0.34s")}
          transform="translate(127.9,0)"
        >
          <path pathLength={1} d="M1.6,7 L1.6,20" />
        </g>
        {/* the i-dot is a fill — dashoffset cannot draw it, so it pops */}
        <circle
          className="brand-logo__pop"
          style={draw("0.42s")}
          cx="129.5"
          cy="2.7"
          r="2"
          fill="currentColor"
          stroke="none"
        />
        <g
          className="brand-logo__stroke"
          style={draw("0.42s")}
          transform="translate(139,0)"
        >
          <path
            pathLength={1}
            d="M0.28,12.1 L10.72,12.1 A5.35,6.5 0 1 0 8.57,18.82"
          />
        </g>
        <g
          className="brand-logo__stroke"
          style={draw("0.5s")}
          transform="translate(154,0)"
        >
          <path
            pathLength={1}
            d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5"
          />
          <path pathLength={1} d="M10.85,0 L10.85,20" />
        </g>
      </g>
      {/* the emerald verdict — the sentence-ending full stop. Its entrance
          delay waits out the last letter's draw: the mark lands only once the
          sentence it punctuates exists. */}
      <circle
        className="brand-logo__node brand-logo__verdict"
        style={node("240ms", "0.9s")}
        cx="172"
        cy="31"
        r="2.8"
        stroke="none"
      />
    </>
  );
}

export function Logo({
  variant = "full",
  className,
  title = "Applied",
}: LogoProps) {
  const mark = variant === "mark";
  return (
    <svg
      className={cn("brand-logo", mark ? "h-7 w-7" : "h-6 w-auto", className)}
      viewBox={mark ? "0 0 48 48" : "0 0 180.8 48"}
      role="img"
      aria-label={title}
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      <Mark />
      {mark ? null : <Wordmark />}
    </svg>
  );
}
