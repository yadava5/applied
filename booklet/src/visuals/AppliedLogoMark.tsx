import React from "react";
import { COLORS } from "../theme";

/**
 * Applied's pipeline mark — three nodes climbing a diagonal: two open cyan
 * rings (extraction layers) resolving into a filled emerald node (the
 * verdict). Hand-transcribed from the 48×48 app-chip region of
 * `logos/applied.svg` so the print/PDF path never fetches an external file;
 * the viewBox is the tight ink box in *source coordinates* so every path
 * stays diffable against the SVG.
 *
 * Two deliberate departures from the source:
 *   • The chip's dark tile is dropped. Its only job is to supply a dark
 *     ground on light contexts — the covers' navy field already is that
 *     ground, and #0A0A0B on #0B1220 would read as a dead square.
 *   • Colors resolve to the booklet's own on-dark accents, not the app's
 *     web palette: rings #06B6D4 → RULES_CYAN, verdict #10B981 →
 *     SETFIT_GREEN, connectors #F7F8F8@.65 → ON_DARK_MUTED. Same semantic
 *     mapping the theme documents (cyan = rules layers, green = verdict).
 */

export type AppliedLogoMarkProps = {
  /** Rendered height in px; width follows the 32:30 ink box. */
  size: number;
};

export const AppliedLogoMark: React.FC<AppliedLogoMarkProps> = ({ size }) => (
  <svg
    width={(size * 32) / 30}
    height={size}
    viewBox="8 9 32 30"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={{ overflow: "visible", flexShrink: 0 }}
  >
    <g strokeLinecap="round">
      <path d="M17.2,30.2 L20.3,27.4" stroke={COLORS.ON_DARK_MUTED} strokeWidth={2} />
      <path d="M27.7,20.7 L30.6,18.1" stroke={COLORS.ON_DARK_MUTED} strokeWidth={2} />
      <circle cx={13.5} cy={33.5} r={3} stroke={COLORS.RULES_CYAN} strokeWidth={2.4} />
      <circle cx={24} cy={24} r={3} stroke={COLORS.RULES_CYAN} strokeWidth={2.4} />
      <circle cx={34.5} cy={14.5} r={4.1} fill={COLORS.SETFIT_GREEN} />
    </g>
  </svg>
);
