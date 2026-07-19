import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { BUILD } from "../content";
import { SourceNote } from "../primitives/SourceNote";

/** Page 26 — the stack. */
export const BuildStackPage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="BUILD"
    sectionColor={SECTION_INK["05_BUILD"]}
    eyebrow={BUILD.stack.eyebrow}
    headline={BUILD.stack.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 17,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "0 0 24px",
        maxWidth: "6.4in",
      }}
    >
      {BUILD.stack.lede}
    </p>

    {/* Stack table */}
    <div style={{ borderTop: `1pt solid ${COLORS.INK}` }}>
      {BUILD.stack.rows.map((r) => (
        <div
          key={r.area}
          style={{
            display: "grid",
            gridTemplateColumns: "1.3in 1fr",
            columnGap: 20,
            padding: "13px 0",
            borderBottom: `0.5pt solid ${COLORS.HAIRLINE}`,
            alignItems: "baseline",
          }}
        >
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9.5,
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: SECTION_INK["05_BUILD"],
            }}
          >
            {r.area}
          </span>
          <div>
            <div
              style={{
                fontFamily: FONTS.SANS,
                fontSize: 14,
                fontWeight: 600,
                letterSpacing: "-0.01em",
                color: COLORS.INK,
                marginBottom: 2,
              }}
            >
              {r.tech}
            </div>
            <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11.5, color: COLORS.INK_MUTED }}>
              {r.note}
            </div>
          </div>
        </div>
      ))}
    </div>

    {/* one-line thesis */}
    <p
      style={{
        fontFamily: FONTS.SANS,
        fontSize: TYPE.body.size,
        lineHeight: TYPE.body.lh,
        letterSpacing: TYPE.body.tracking,
        color: COLORS.INK,
        margin: "24px 0 0",
        maxWidth: "6.2in",
      }}
    >
      Two homes for one model: it is <b>trained</b> in Python against the
      FastAPI backend and the macOS app, and it <b>ships</b> as a portable int8
      ONNX served by the Next.js 16 web app — the same three-layer verdict on
      either side.
    </p>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{BUILD.stack.source}</SourceNote>
    </div>
  </BodyPage>
);
