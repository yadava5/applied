import React from "react";
import { COLORS, FONTS } from "../theme";

/**
 * "source · …" citation line — the booklet's honesty rail. Mono, small, sits
 * at the foot of a data block so every printed number can be traced back to a
 * file:line in the repo.
 */
export const SourceNote: React.FC<{
  children: React.ReactNode;
  color?: string;
  style?: React.CSSProperties;
}> = ({ children, color = COLORS.INK_SUBTLE, style }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 6,
      fontFamily: FONTS.MONO,
      fontSize: 7.5,
      fontWeight: 500,
      letterSpacing: "0.06em",
      color,
      ...style,
    }}
  >
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 5,
        height: 5,
        borderRadius: 1,
        border: `0.75pt solid ${color}`,
      }}
    />
    <span style={{ textTransform: "lowercase" }}>{children}</span>
  </div>
);
