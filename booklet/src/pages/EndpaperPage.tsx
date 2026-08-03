import React from "react";
import { Page } from "../primitives/Page";
import { COLORS, FONTS, SECTION } from "../theme";
import { ABSTRACT, BRAND, MASTHEAD, CHAPTERS } from "../content";

/**
 * Welcome / endpaper (page 02). A quiet opening spread: the masthead kicker,
 * a serif "Welcome.", the ≤80-word abstract, and a three-fact strip that
 * previews the whole system before the reader turns into chapter one.
 */
export const EndpaperPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <Page
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="FRONTMATTER"
    sectionColor={COLORS.INK_MUTED}
    hideFooter
  >
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Masthead */}
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: COLORS.INK_MUTED,
        }}
      >
        {MASTHEAD.volume}
      </div>

      <div style={{ flex: 1 }} />

      {/* Greeting + abstract */}
      <div style={{ maxWidth: "6.2in" }}>
        <h1
          style={{
            fontFamily: FONTS.SERIF,
            fontStyle: "italic",
            fontSize: 68,
            fontWeight: 400,
            lineHeight: 1,
            color: COLORS.INK,
            margin: "0 0 22px",
          }}
        >
          {ABSTRACT.greeting}
        </h1>
        <p
          style={{
            fontFamily: FONTS.SANS,
            fontSize: 15,
            fontWeight: 400,
            lineHeight: 1.6,
            letterSpacing: "-0.005em",
            color: COLORS.INK,
            margin: 0,
          }}
        >
          {ABSTRACT.body}
        </p>
      </div>

      <div style={{ flex: 0.55 }} />

      {/* In this volume — a compact six-chapter preview */}
      <div>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: COLORS.INK_MUTED,
            marginBottom: 12,
          }}
        >
          In this volume
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", columnGap: 12 }}>
          {CHAPTERS.map((ch) => (
            <div key={ch.num} style={{ display: "flex", flexDirection: "column", gap: 5, borderTop: `2px solid ${SECTION[ch.sectionKey]}`, paddingTop: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: SECTION[ch.sectionKey], flexShrink: 0 }} />
                <span style={{ fontFamily: FONTS.MONO, fontSize: 9, fontWeight: 700, color: COLORS.INK, fontVariantNumeric: "tabular-nums" }}>{ch.num}</span>
              </div>
              <span style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 14, color: COLORS.INK, lineHeight: 1 }}>{ch.name}</span>
              <span style={{ fontFamily: FONTS.MONO, fontSize: 7.5, color: COLORS.INK_SUBTLE, letterSpacing: "0.02em" }}>pp. {ch.pages}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ flex: 0.6 }} />

      {/* Three-fact strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 0,
          borderTop: `1pt solid ${COLORS.INK}`,
          borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
        }}
      >
        <Fact value="3" unit="layers" note="rules · e5 · SetFit" accent={COLORS.RULES_DEEP} />
        <Fact value="0.85" unit="gate" note="below it, a human decides" accent={COLORS.GATE_DEEP} first={false} />
        <Fact value="22.8" unit="MB · in-browser" note="int8 ONNX · zero servers" accent={COLORS.E5_DEEP} first={false} />
      </div>

      {/* Kicker */}
      <p
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 13,
          lineHeight: 1.4,
          color: COLORS.INK_MUTED,
          margin: "16px 0 0",
          maxWidth: "6in",
        }}
      >
        {MASTHEAD.kicker}
      </p>

      <div
        style={{
          marginTop: 12,
          fontFamily: FONTS.MONO,
          fontSize: 8.5,
          fontWeight: 500,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: COLORS.INK_SUBTLE,
        }}
      >
        {BRAND.author} · {BRAND.year} · {BRAND.liveUrl}
      </div>
    </div>
  </Page>
);

const Fact: React.FC<{
  value: string;
  unit: string;
  note: string;
  accent: string;
  first?: boolean;
}> = ({ value, unit, note, accent, first = true }) => (
  <div
    style={{
      padding: "14px 16px",
      borderLeft: first ? "none" : `0.5pt solid ${COLORS.HAIRLINE}`,
      display: "flex",
      flexDirection: "column",
      gap: 4,
    }}
  >
    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 30,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          color: accent,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
      <span
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: COLORS.INK_MUTED,
        }}
      >
        {unit}
      </span>
    </div>
    <span
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 11,
        color: COLORS.INK_MUTED,
      }}
    >
      {note}
    </span>
  </div>
);
