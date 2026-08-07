import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { PROOF } from "../content";
import { SourceNote } from "../primitives/SourceNote";

/** Page 19 — 0.979 macro-F1, CI-gated. */
export const ProofF1Page: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => {
  const { f1 } = PROOF;
  return (
    <BodyPage
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel="PROOF"
      sectionColor={SECTION_INK["04_PROOF"]}
      eyebrow={f1.eyebrow}
      headline={f1.headline}
    >
      {/* Hero number */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24, marginTop: 6 }}>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: TYPE.metricHero.size,
            fontWeight: 700,
            letterSpacing: TYPE.metricHero.tracking,
            lineHeight: 0.9,
            color: COLORS.SETFIT_DEEP,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {f1.hero}
        </div>
        <div style={{ paddingBottom: 8 }}>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
              maxWidth: "2.4in",
              lineHeight: 1.35,
            }}
          >
            {f1.heroLabel}
          </div>
        </div>
      </div>

      {/* Floor bar — full 0–1 scale above, the 0.90–1.00 window magnified below,
          both labelled so neither the honesty nor the floor clearance is lost.
          The floor marker protrudes onto the paper (red-on-white measures 4.8:1;
          red-on-the-green-fill drops to 2.1:1 under deuteranopia). */}
      <div style={{ marginTop: 24, maxWidth: "6.4in" }}>
        <svg viewBox="0 0 640 104" width="100%" style={{ display: "block", overflow: "visible" }}>
          <defs>
            <clipPath id="f1-detail-track">
              <rect x={0} y={52} width={640} height={26} rx={5} />
            </clipPath>
          </defs>

          {/* full scale 0–1 */}
          <text x={0} y={9} fontFamily={FONTS.MONO} fontSize={6.5} fontWeight={600} letterSpacing="0.1em" fill={COLORS.INK_MUTED}>
            FULL SCALE 0–1.00
          </text>
          <text x={640} y={9} textAnchor="end" fontFamily={FONTS.MONO} fontSize={6.5} fontWeight={600} letterSpacing="0.1em" fill={COLORS.INK_MUTED}>
            DETAIL · 0.90–1.00
          </text>
          <rect x={0} y={16} width={640} height={7} rx={3.5} fill={COLORS.SURFACE} />
          <rect x={0} y={16} width={0.9791 * 640} height={7} rx={3.5} fill={COLORS.SETFIT_GREEN} opacity={0.85} />
          {/* the magnified window, bracketed on the full scale */}
          <rect x={0.9 * 640} y={13} width={0.1 * 640} height={13} rx={2} fill="none" stroke={COLORS.INK} strokeWidth={1} />
          {/* window → detail guides */}
          <line x1={0.9 * 640} y1={26} x2={0} y2={52} stroke={COLORS.HAIRLINE} strokeWidth={1} />
          <line x1={640} y1={26} x2={640} y2={52} stroke={COLORS.HAIRLINE} strokeWidth={1} />

          {/* detail track: 0.90–1.00 */}
          <rect x={0} y={52} width={640} height={26} rx={5} fill={COLORS.SURFACE} />
          <g clipPath="url(#f1-detail-track)">
            <rect x={0} y={52} width={((0.9791 - 0.9) / 0.1) * 640} height={26} fill={COLORS.SETFIT_GREEN} opacity={0.85} />
          </g>
          {/* the score, marked where the fill ends */}
          <line x1={((0.9791 - 0.9) / 0.1) * 640} y1={46} x2={((0.9791 - 0.9) / 0.1) * 640} y2={78} stroke={COLORS.SETFIT_DEEP} strokeWidth={2} />
          <text x={((0.9791 - 0.9) / 0.1) * 640} y={42} textAnchor="middle" fontFamily={FONTS.MONO} fontSize={10} fontWeight={700} fill={COLORS.SETFIT_DEEP} style={{ fontVariantNumeric: "tabular-nums" }}>
            0.979
          </text>
          {/* floor at 0.95 — pointer + overshoot live on the paper, not the fill */}
          <polygon points="315.5,45 324.5,45 320,51.5" fill={COLORS.DANGER} />
          <line x1={320} y1={51} x2={320} y2={84} stroke={COLORS.DANGER} strokeWidth={2} />

          {/* detail ticks */}
          <g fontFamily={FONTS.MONO} fontSize={8} style={{ fontVariantNumeric: "tabular-nums" }}>
            <text x={0} y={97} fontWeight={500} fill={COLORS.INK_MUTED}>0.90</text>
            <text x={320} y={97} textAnchor="middle" fontWeight={700} fill={COLORS.DANGER}>0.95 floor</text>
            <text x={640} y={97} textAnchor="end" fontWeight={500} fill={COLORS.INK_MUTED}>1.00</text>
          </g>
        </svg>
      </div>

      <p
        style={{
          fontFamily: FONTS.SANS,
          fontSize: TYPE.body.size,
          lineHeight: TYPE.body.lh,
          letterSpacing: TYPE.body.tracking,
          color: COLORS.INK,
          margin: "24px 0 0",
          maxWidth: "6.4in",
        }}
      >
        {f1.body}
      </p>

      {/* CI gate block */}
      <div
        style={{
          marginTop: 24,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          columnGap: 20,
          alignItems: "center",
          borderTop: `1pt solid ${COLORS.INK}`,
          paddingTop: 18,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: TYPE.metricMedium.size,
            fontWeight: 700,
            color: COLORS.DANGER,
            fontVariantNumeric: "tabular-nums",
            lineHeight: 1,
          }}
        >
          ≥ {f1.ciValue}
        </div>
        <div>
          <div
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
              marginBottom: 4,
            }}
          >
            {f1.ciLabel}
          </div>
          <p style={{ fontFamily: FONTS.SANS, fontSize: 11, lineHeight: 1.42, color: COLORS.INK, margin: 0 }}>
            {f1.ciBody}
          </p>
        </div>
      </div>

      <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in", display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          style={{
            fontFamily: FONTS.MONO,
            fontSize: 8.5,
            color: COLORS.INK_MUTED,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {f1.exact}
        </div>
        <SourceNote>{f1.source}</SourceNote>
      </div>
    </BodyPage>
  );
};
