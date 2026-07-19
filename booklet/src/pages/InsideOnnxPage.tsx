import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { INSIDE } from "../content";
import { OnnxCompress } from "../visuals/OnnxCompress";
import { SourceNote } from "../primitives/SourceNote";

/** Page 16 — the int8 ONNX export, to scale. */
export const InsideOnnxPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="INSIDE"
    sectionColor={SECTION_INK["03_INSIDE"]}
    eyebrow={INSIDE.onnx.eyebrow}
    headline={INSIDE.onnx.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 17,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "0 0 8px",
        maxWidth: "6.4in",
      }}
    >
      {INSIDE.onnx.lede}
    </p>

    <p
      style={{
        fontFamily: FONTS.SANS,
        fontSize: TYPE.body.size,
        lineHeight: TYPE.body.lh,
        letterSpacing: TYPE.body.tracking,
        color: COLORS.INK,
        margin: "0 0 28px",
        maxWidth: "6.4in",
      }}
    >
      {INSIDE.onnx.body}
    </p>

    <OnnxCompress />

    {/* What quantization means, briefly */}
    <div
      style={{
        marginTop: 30,
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 0,
        borderTop: `1pt solid ${COLORS.INK}`,
      }}
    >
      <MiniFact
        head="float32 → int8"
        body="weights drop from 32-bit floats to 8-bit integers."
        first
      />
      <MiniFact head="dynamic quant" body="no calibration set; quantized at export time." />
      <MiniFact head="fits a tab" body="small enough to fetch once and cache." />
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{INSIDE.onnx.source}</SourceNote>
    </div>
  </BodyPage>
);

const MiniFact: React.FC<{ head: string; body: string; first?: boolean }> = ({
  head,
  body,
  first = false,
}) => (
  <div
    style={{
      padding: "14px 16px",
      borderLeft: first ? "none" : `0.5pt solid ${COLORS.HAIRLINE}`,
    }}
  >
    <div
      style={{
        fontFamily: FONTS.MONO,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.04em",
        color: SECTION_INK["03_INSIDE"],
        marginBottom: 5,
      }}
    >
      {head}
    </div>
    <div
      style={{
        fontFamily: FONTS.SANS,
        fontSize: 10.5,
        lineHeight: 1.4,
        color: COLORS.INK_MUTED,
      }}
    >
      {body}
    </div>
  </div>
);
