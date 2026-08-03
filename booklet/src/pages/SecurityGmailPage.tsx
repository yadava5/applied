import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { SECURITY } from "../content";
import { SourceNote } from "../primitives/SourceNote";

/** Page 26 — Gmail: least-privilege, encrypted, revocable, invite-gated. */
export const SecurityGmailPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { gmail } = SECURITY;
  const ink = SECTION_INK["05_SECURITY"];
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="SECURITY"
      sectionColor={ink}
      eyebrow={gmail.eyebrow}
      headline={gmail.headline}
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
        {gmail.lede}
      </p>

      {/* Permission matrix — one scope granted, the rest never asked for */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.15fr 1.85fr",
          gap: 0,
          border: `0.5pt solid ${COLORS.HAIRLINE}`,
          borderRadius: 6,
          overflow: "hidden",
        }}
      >
        {/* Granted */}
        <div style={{ padding: "13px 15px", background: COLORS.SECURITY_TINT, borderRight: `0.5pt solid ${COLORS.HAIRLINE}` }}>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 8,
              fontWeight: 700,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: ink,
              marginBottom: 8,
            }}
          >
            granted
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              style={{
                width: 18,
                height: 18,
                borderRadius: 4,
                background: COLORS.SECURITY_INDIGO,
                display: "grid",
                placeItems: "center",
                flexShrink: 0,
              }}
            >
              <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden>
                <path d="M2.5 6 L5 8.5 L9.5 3.5" fill="none" stroke={COLORS.PAPER} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span style={{ fontFamily: FONTS.MONO, fontSize: 13, fontWeight: 700, color: COLORS.INK }}>{gmail.scopeGranted.label}</span>
          </div>
          <div style={{ fontFamily: FONTS.SANS, fontSize: 9.5, lineHeight: 1.35, color: COLORS.INK_MUTED, marginTop: 6 }}>
            {gmail.scopeGranted.note}
          </div>
        </div>

        {/* Withheld */}
        <div style={{ padding: "13px 15px" }}>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 8,
              fontWeight: 700,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
              marginBottom: 8,
            }}
          >
            never requested
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 7 }}>
            {gmail.scopeWithheld.map((cap) => (
              <div key={cap} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <svg width={13} height={13} viewBox="0 0 14 14" aria-hidden style={{ flexShrink: 0 }}>
                  <circle cx={7} cy={7} r={6} fill="none" stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1} />
                  <line x1={4.5} y1={4.5} x2={9.5} y2={9.5} stroke={COLORS.HAIRLINE_STRONG} strokeWidth={1} strokeLinecap="round" />
                </svg>
                <span
                  style={{
                    fontFamily: FONTS.MONO,
                    fontSize: 10,
                    fontWeight: 500,
                    color: COLORS.INK_MUTED,
                    textDecoration: "line-through",
                    textDecorationColor: COLORS.HAIRLINE_STRONG,
                  }}
                >
                  {cap}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11, lineHeight: 1.35, color: COLORS.INK_SUBTLE, marginTop: 10 }}>
            {gmail.scopeCaption}
          </div>
        </div>
      </div>

      {/* Three protections */}
      <div style={{ marginTop: 18, display: "flex", flexDirection: "column" }}>
        {gmail.rows.map((r, i) => (
          <div
            key={r.k}
            style={{
              display: "grid",
              gridTemplateColumns: "1.35in 1fr",
              columnGap: 16,
              alignItems: "baseline",
              padding: "10px 0",
              borderTop: i === 0 ? `1pt solid ${COLORS.INK}` : `0.5pt solid ${COLORS.HAIRLINE}`,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.MONO,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: ink,
              }}
            >
              {r.k}
            </span>
            <span style={{ fontFamily: FONTS.SANS, fontSize: 10.5, lineHeight: 1.42, color: COLORS.INK }}>{r.v}</span>
          </div>
        ))}
      </div>

      {/* Beta / invite-only callout */}
      <div
        style={{
          marginTop: 18,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          columnGap: 18,
          alignItems: "center",
          border: `0.75pt dashed ${COLORS.SECURITY_INDIGO}`,
          borderRadius: 6,
          background: COLORS.SECURITY_TINT,
          padding: "12px 16px",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingRight: 16, borderRight: `0.5pt solid ${COLORS.HAIRLINE}` }}>
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: TYPE.metricMedium.size,
              fontWeight: 700,
              lineHeight: 1,
              color: ink,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {gmail.beta.seats}
          </span>
          <span style={{ fontFamily: FONTS.MONO, fontSize: 7.5, letterSpacing: "0.1em", textTransform: "uppercase", color: COLORS.INK_MUTED, marginTop: 3 }}>
            test-user cap
          </span>
        </div>
        <div>
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
            {gmail.beta.label}
          </div>
          <p style={{ fontFamily: FONTS.SANS, fontSize: 10.5, lineHeight: 1.4, color: COLORS.INK, margin: 0 }}>{gmail.beta.body}</p>
          <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 10.5, color: COLORS.INK_SUBTLE, marginTop: 4 }}>
            {gmail.beta.seatsNote}
          </div>
        </div>
      </div>

      <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
        <SourceNote>{gmail.source}</SourceNote>
      </div>
    </BodyPage>
  );
};
