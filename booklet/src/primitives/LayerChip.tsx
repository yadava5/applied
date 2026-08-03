import React from "react";
import { COLORS, FONTS } from "../theme";

/**
 * A classifier-layer chip: an accent dot, the layer index, and its label.
 * Mirrors the legend rows in the app's DecisionTrace. Renders on light pages
 * (default) or dark device panels (`onDark`).
 */
export const LayerChip: React.FC<{
  n: string;
  label: string;
  accent: string;
  onDark?: boolean;
  style?: React.CSSProperties;
}> = ({ n, label, accent, onDark = false, style }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      fontFamily: FONTS.MONO,
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: "0.04em",
      color: onDark ? COLORS.ON_DARK_MUTED : COLORS.INK_MUTED,
      ...style,
    }}
  >
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: accent,
        boxShadow: `0 0 10px -2px ${accent}`,
      }}
    />
    <span style={{ color: onDark ? COLORS.ON_DARK_SUBTLE : COLORS.INK_SUBTLE }}>{n}</span>
    <span style={{ color: onDark ? COLORS.ON_DARK : COLORS.INK }}>{label}</span>
  </span>
);
