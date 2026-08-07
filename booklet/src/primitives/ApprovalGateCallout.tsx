import React from "react";
import { COLORS, FONTS, TYPE } from "../theme";

/**
 * Confidence-gate callout — a dotted border, a Monaspace eyebrow, and an
 * Instrument Serif italic body. Conceptually mirrors Applied's 0.85 gate:
 * below it, nothing is auto-filed and a human presides.
 */
export const ApprovalGateCallout: React.FC<{
  children: React.ReactNode;
  label?: string;
  accent?: string;
  width?: number | string;
  style?: React.CSSProperties;
}> = ({
  children,
  label = "BELOW THE GATE · A HUMAN DECIDES",
  accent = COLORS.GATE_DEEP,
  width = "100%",
  style,
}) => (
  <div
    style={{
      border: `0.75pt dotted ${accent}`,
      padding: "14px 18px",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      width,
      boxSizing: "border-box",
      ...style,
    }}
  >
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: TYPE.approvalLabel.size,
        fontWeight: TYPE.approvalLabel.weight,
        letterSpacing: TYPE.approvalLabel.tracking,
        textTransform: "uppercase",
        color: accent,
        lineHeight: 1,
      }}
    >
      {label}
    </div>
    <div
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 16,
        fontWeight: 400,
        letterSpacing: "0",
        lineHeight: 1.3,
        color: COLORS.INK,
      }}
    >
      {children}
    </div>
  </div>
);
