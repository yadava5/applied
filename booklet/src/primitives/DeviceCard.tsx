import React from "react";
import { COLORS, FONTS } from "../theme";

/**
 * A dark "device" panel — the booklet's recurring way to drop a slab of the
 * app's own dark identity into a light editorial page. Optional browser-chrome
 * bar (three dots + a URL line) frames anything meant to read as running
 * software: the decision trace, the in-browser classifier, the cascade.
 */
export const DeviceCard: React.FC<{
  children: React.ReactNode;
  chrome?: string | false;
  accent?: string;
  padded?: boolean;
  style?: React.CSSProperties;
}> = ({ children, chrome = false, accent = COLORS.RULES_CYAN, padded = true, style }) => (
  <div
    style={{
      background: COLORS.GROUND,
      border: `1px solid ${COLORS.GROUND_ELEVATED}`,
      borderRadius: 8,
      overflow: "hidden",
      boxShadow: "0 1px 0 rgba(255,255,255,0.03) inset",
      ...style,
    }}
  >
    {chrome !== false && (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          borderBottom: `1px solid ${COLORS.ON_DARK_HAIRLINE}`,
        }}
      >
        <span style={{ display: "inline-flex", gap: 5 }}>
          {[COLORS.GATE_AMBER, COLORS.STEEL, COLORS.SETFIT_GREEN].map((c) => (
            <span
              key={c}
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: c,
                opacity: 0.55,
              }}
            />
          ))}
        </span>
        <span
          style={{
            flex: 1,
            marginLeft: 6,
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            letterSpacing: "0.04em",
            color: COLORS.ON_DARK_SUBTLE,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {chrome}
        </span>
        <span
          aria-hidden
          style={{
            width: 20,
            height: 4,
            borderRadius: 2,
            background: accent,
            opacity: 0.6,
          }}
        />
      </div>
    )}
    <div style={{ padding: padded ? 16 : 0 }}>{children}</div>
  </div>
);
