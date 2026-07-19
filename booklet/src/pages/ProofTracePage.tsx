import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, SECTION_INK } from "../theme";
import { PROOF, BRAND } from "../content";
import { DecisionTrace } from "../visuals/DecisionTrace";
import { DeviceCard } from "../primitives/DeviceCard";

/** Page 21 — the decision trace (the signature visual), printed. */
export const ProofTracePage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="PROOF"
    sectionColor={SECTION_INK["04_PROOF"]}
    eyebrow={PROOF.trace.eyebrow}
    headline={PROOF.trace.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 16,
        lineHeight: 1.38,
        color: COLORS.INK_MUTED,
        margin: "0 0 20px",
        maxWidth: "6.4in",
      }}
    >
      {PROOF.trace.lede}
    </p>

    <DeviceCard chrome={`${BRAND.liveUrl}/demo · review queue`} accent={COLORS.SETFIT_GREEN}>
      <DecisionTrace />
    </DeviceCard>

    <div
      style={{
        marginTop: 16,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 16,
      }}
    >
      <span
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: "0.06em",
          color: COLORS.INK_SUBTLE,
        }}
      >
        {PROOF.trace.illustrativeNote}
      </span>
      <span
        style={{
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: 13,
          color: COLORS.INK_MUTED,
        }}
      >
        the layer that fired lights; the gate decides who files.
      </span>
    </div>
  </BodyPage>
);
