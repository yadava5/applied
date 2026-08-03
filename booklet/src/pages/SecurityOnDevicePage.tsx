import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, SECTION, SECTION_INK, type SectionKey } from "../theme";
import { SECURITY } from "../content";
import { SourceNote } from "../primitives/SourceNote";

/** Page 25 — on-device: the in-browser model and the on-device import. */
export const SecurityOnDevicePage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { onDevice } = SECURITY;
  const ink = SECTION_INK["05_SECURITY"];
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="SECURITY"
      sectionColor={ink}
      eyebrow={onDevice.eyebrow}
      headline={onDevice.headline}
      align="top"
    >
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 17,
          lineHeight: 1.35,
          color: COLORS.INK_MUTED,
          margin: "0 0 18px",
          maxWidth: "6.4in",
        }}
      >
        {onDevice.lede}
      </p>

      {/* Two on-device modes */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 18 }}>
        {onDevice.modes.map((m) => {
          const accent = SECTION[m.accentKey as SectionKey];
          const accentInk = SECTION_INK[m.accentKey as SectionKey];
          return (
            <div
              key={m.tag}
              style={{
                border: `0.5pt solid ${COLORS.HAIRLINE}`,
                borderTop: `3px solid ${accent}`,
                borderRadius: 6,
                background: COLORS.PAPER_ELEVATED,
                padding: "14px 16px",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <span
                style={{
                  alignSelf: "flex-start",
                  fontFamily: FONTS.MONO,
                  fontSize: 8,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: accentInk,
                  background: `${accent}1f`,
                  border: `0.5pt solid ${accent}`,
                  borderRadius: 3,
                  padding: "3px 7px",
                }}
              >
                {m.tag}
              </span>
              <div style={{ fontFamily: FONTS.SANS, fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em", color: COLORS.INK, lineHeight: 1.15 }}>
                {m.title}
              </div>
              <p style={{ fontFamily: FONTS.SANS, fontSize: 10.5, lineHeight: 1.4, color: COLORS.INK_MUTED, margin: 0 }}>{m.body}</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 2 }}>
                {m.checks.map((c) => (
                  <div key={c} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <svg width={12} height={12} viewBox="0 0 14 14" aria-hidden style={{ flexShrink: 0 }}>
                      <circle cx={7} cy={7} r={6.2} fill="none" stroke={accent} strokeWidth={1} />
                      <path d="M4 7 L6 9 L10 5" fill="none" stroke={accent} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <span style={{ fontFamily: FONTS.MONO, fontSize: 9, letterSpacing: "0.02em", color: COLORS.INK }}>{c}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Supported import formats */}
      <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: ink,
          }}
        >
          import reads
        </span>
        {onDevice.formats.map((f) => (
          <span
            key={f}
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              fontWeight: 600,
              color: COLORS.INK,
              background: COLORS.SURFACE,
              border: `0.5pt solid ${COLORS.HAIRLINE}`,
              borderRadius: 999,
              padding: "4px 11px",
            }}
          >
            {f}
          </span>
        ))}
        <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11.5, color: COLORS.INK_SUBTLE }}>
          → nothing uploaded
        </span>
      </div>

      {/* Honesty note */}
      <div
        style={{
          marginTop: 20,
          borderLeft: `2.5px solid ${ink}`,
          paddingLeft: 14,
          maxWidth: "6.4in",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: ink,
            marginBottom: 4,
          }}
        >
          honest scope
        </div>
        <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 12.5, lineHeight: 1.42, color: COLORS.INK_MUTED }}>
          {onDevice.honest}
        </div>
      </div>

      {/* On-device import — the round-trip that never leaves the tab */}
      <div
        style={{
          marginTop: 24,
          border: `0.5pt solid ${COLORS.HAIRLINE}`,
          borderRadius: 6,
          background: COLORS.PAPER_ELEVATED,
          padding: "16px 18px",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: ink,
            marginBottom: 14,
          }}
        >
          on-device import — the whole round-trip is one tab
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <FlowStep n="1" title="Drop the file" sub="MBOX / .eml / JSON — from disk" />
          <FlowArrow />
          <FlowStep n="2" title="Parse in the tab" sub="FileReader · dependency-free · no upload" />
          <FlowArrow />
          <FlowStep n="3" title="Classify in the tab" sub="layer-1 rules · verdicts appear live" />
          <FlowArrow />
          <FlowTerminal />
        </div>
      </div>

      <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
        <SourceNote>{onDevice.source}</SourceNote>
      </div>
    </BodyPage>
  );
};

const FlowStep: React.FC<{ n: string; title: string; sub: string }> = ({ n, title, sub }) => (
  <div
    style={{
      flex: 1,
      minWidth: 0,
      display: "flex",
      flexDirection: "column",
      gap: 4,
      padding: "10px 12px",
      borderRadius: 5,
      border: `0.5pt solid ${COLORS.HAIRLINE}`,
      background: COLORS.PAPER,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: COLORS.SECURITY_INDIGO,
          color: COLORS.PAPER,
          display: "grid",
          placeItems: "center",
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 700,
          flexShrink: 0,
        }}
      >
        {n}
      </span>
      <span style={{ fontFamily: FONTS.SANS, fontSize: 11, fontWeight: 700, color: COLORS.INK, letterSpacing: "-0.01em" }}>{title}</span>
    </div>
    <span style={{ fontFamily: FONTS.MONO, fontSize: 7.5, letterSpacing: "0.02em", color: COLORS.INK_MUTED, lineHeight: 1.35 }}>{sub}</span>
  </div>
);

const FlowArrow: React.FC = () => (
  <svg width={18} height={10} viewBox="0 0 18 10" aria-hidden style={{ flexShrink: 0 }}>
    <line x1={1} y1={5} x2={13} y2={5} stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1.2} strokeLinecap="round" />
    <path d="M10 2 L14 5 L10 8" fill="none" stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const FlowTerminal: React.FC = () => (
  <div
    style={{
      flexShrink: 0,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 3,
      padding: "10px 12px",
      borderRadius: 5,
      border: `0.5pt solid ${COLORS.SETFIT_GREEN}`,
      background: COLORS.SETFIT_TINT,
      minWidth: 74,
    }}
  >
    <span style={{ fontFamily: FONTS.MONO, fontSize: 8, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: COLORS.SETFIT_DEEP, textAlign: "center", lineHeight: 1.3 }}>
      never
      <br />
      leaves device
    </span>
  </div>
);
