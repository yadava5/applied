import React from "react";
import { COLORS, FONTS, SECTION, SECTION_INK, type SectionKey } from "../theme";
import { LAYERS } from "../content";

/**
 * The signature HOW diagram — the 3-layer cascade drawn as a vertical spine.
 * An email enters at the top; each layer fires (and stops the cascade) if it
 * clears its accept threshold, otherwise it falls through to the next. At the
 * foot sits the 0.85 confidence gate with its two outcomes. Layer accents map
 * to the app's own viz tokens (cyan / violet / green), amber for the gate.
 */

const NODE = 36;

export const LayerCascade: React.FC = () => (
  <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
    <EntryNode />

    {LAYERS.map((layer) => {
      const accent = SECTION[layer.accentKey as SectionKey];
      const accentInk = SECTION_INK[layer.accentKey as SectionKey];
      return (
        <Row key={layer.id} nodeColor={accent} nodeLabel={layer.n} connector>
          <div
            style={{
              borderLeft: `3px solid ${accent}`,
              background: COLORS.PAPER_ELEVATED,
              borderTop: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderRight: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderRadius: 4,
              padding: "13px 14px",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    fontFamily: FONTS.SANS,
                    fontSize: 15,
                    fontWeight: 700,
                    letterSpacing: "-0.01em",
                    color: COLORS.INK,
                  }}
                >
                  {layer.label}
                </span>
                <span
                  style={{
                    fontFamily: FONTS.SERIF,
                    fontStyle: "italic",
                    fontSize: 11,
                    color: COLORS.INK_MUTED,
                  }}
                >
                  {layer.note}
                </span>
              </div>
              <div
                style={{
                  fontFamily: FONTS.MONO,
                  fontSize: 8.5,
                  letterSpacing: "0.02em",
                  color: COLORS.INK_MUTED,
                  marginTop: 2,
                }}
              >
                {layer.model}
              </div>
            </div>
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.02em",
                color: accentInk,
                background: `${accent}22`,
                border: `0.5pt solid ${accent}`,
                borderRadius: 3,
                padding: "3px 6px",
                whiteSpace: "nowrap",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {layer.accept}
            </span>
          </div>
          <FallHint>if below, fall through ↓</FallHint>
        </Row>
      );
    })}

    <GateRow />
  </div>
);

// --- Entry node -------------------------------------------------------------

const EntryNode: React.FC = () => (
  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 2 }}>
    <div
      style={{
        width: NODE,
        display: "flex",
        justifyContent: "center",
      }}
    >
      <EnvelopeMark size={20} color={COLORS.INK} />
    </div>
    <span
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: COLORS.INK_MUTED,
      }}
    >
      one email enters
    </span>
  </div>
);

// --- A cascade row: spine node + connector + content ------------------------

const Row: React.FC<{
  nodeColor: string;
  nodeLabel: string;
  connector: boolean;
  children: React.ReactNode;
}> = ({ nodeColor, nodeLabel, children }) => (
  <div style={{ display: "flex", gap: 14, alignItems: "stretch" }}>
    {/* spine column */}
    <div
      style={{
        width: NODE,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div style={{ width: 2, height: 16, background: COLORS.HAIRLINE_STRONG }} />
      <div
        style={{
          width: NODE,
          height: NODE,
          borderRadius: "50%",
          background: nodeColor,
          color: COLORS.GROUND,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: FONTS.MONO,
          fontSize: 15,
          fontWeight: 700,
          boxShadow: `0 0 12px -3px ${nodeColor}`,
          flexShrink: 0,
        }}
      >
        {nodeLabel}
      </div>
      <div style={{ width: 2, flex: 1, minHeight: 16, background: COLORS.HAIRLINE_STRONG }} />
    </div>
    {/* content */}
    <div style={{ flex: 1, paddingBottom: 16, display: "flex", flexDirection: "column", gap: 5 }}>
      {children}
    </div>
  </div>
);

const FallHint: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontFamily: FONTS.MONO,
      fontSize: 7.5,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: COLORS.INK_SUBTLE,
      paddingLeft: 2,
    }}
  >
    {children}
  </div>
);

// --- Gate row (bottom) ------------------------------------------------------

const GateRow: React.FC = () => (
  <div style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
    <div style={{ width: NODE, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ width: 2, height: 10, background: COLORS.HAIRLINE_STRONG }} />
      <div
        style={{
          width: NODE,
          height: NODE,
          background: COLORS.GATE_AMBER,
          color: COLORS.GROUND,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: FONTS.MONO,
          fontSize: 15,
          fontWeight: 700,
          transform: "rotate(45deg)",
          boxShadow: `0 0 12px -3px ${COLORS.GATE_AMBER}`,
        }}
      >
        <span style={{ transform: "rotate(-45deg)" }}>◇</span>
      </div>
    </div>
    <div style={{ flex: 1 }}>
      <div
        style={{
          border: `0.75pt dotted ${COLORS.GATE_DEEP}`,
          borderRadius: 4,
          padding: "14px 16px",
          background: COLORS.GATE_TINT,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: COLORS.GATE_DEEP,
            marginBottom: 8,
          }}
        >
          Confidence gate · 0.85
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Outcome
            color={COLORS.SETFIT_DEEP}
            head="≥ 0.85"
            body="auto-file, if the employer is named"
          />
          <Outcome
            color={COLORS.GATE_DEEP}
            head="< 0.85"
            body="a human decides · needs_review"
          />
        </div>
      </div>
    </div>
  </div>
);

const Outcome: React.FC<{ color: string; head: string; body: string }> = ({
  color,
  head,
  body,
}) => (
  <div
    style={{
      flex: 1,
      background: COLORS.PAPER,
      border: `0.5pt solid ${color}`,
      borderRadius: 3,
      padding: "6px 8px",
    }}
  >
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 11,
        fontWeight: 700,
        color,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {head}
    </div>
    <div
      style={{
        fontFamily: FONTS.SANS,
        fontSize: 9,
        fontWeight: 500,
        color: COLORS.INK,
        lineHeight: 1.25,
        marginTop: 2,
      }}
    >
      {body}
    </div>
  </div>
);

// --- Envelope glyph ---------------------------------------------------------

export const EnvelopeMark: React.FC<{ size?: number; color?: string; opacity?: number }> = ({
  size = 16,
  color = COLORS.INK,
  opacity = 1,
}) => (
  <svg width={size} height={size * 0.72} viewBox="0 0 25 18" aria-hidden opacity={opacity}>
    <rect x={1} y={1} width={23} height={16} rx={2} fill="none" stroke={color} strokeWidth={1.4} />
    <path d="M1.5 2 L12.5 10 L23.5 2" fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
