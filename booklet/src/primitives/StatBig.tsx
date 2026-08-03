import React from "react";
import { COLORS, FONTS, TYPE } from "../theme";

/**
 * A single large metric — mono, tabular, on one of the metric tiers. Used for
 * hero numbers (0.979, 22.8 MB, 201). Label sits below in mono uppercase.
 */
export const StatBig: React.FC<{
  value: string;
  label: string;
  tier?: "metricHero" | "metricLarge" | "metricMedium" | "metricSmall";
  color?: string;
  align?: "left" | "center";
  style?: React.CSSProperties;
}> = ({ value, label, tier = "metricLarge", color = COLORS.INK, align = "left", style }) => {
  const t = TYPE[tier];
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        alignItems: align === "center" ? "center" : "flex-start",
        textAlign: align,
        ...style,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: t.size,
          fontWeight: t.weight,
          letterSpacing: t.tracking,
          lineHeight: t.lh,
          color,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: COLORS.INK_MUTED,
          maxWidth: "3in",
        }}
      >
        {label}
      </div>
    </div>
  );
};
