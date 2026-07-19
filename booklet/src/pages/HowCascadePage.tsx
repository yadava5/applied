import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { HOW } from "../content";
import { LayerCascade } from "../visuals/LayerCascade";
import { SourceNote } from "../primitives/SourceNote";

/** Page 09 — the three-layer cascade (HOW hero). */
export const HowCascadePage: React.FC<{
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
}> = ({ parity, pageNumber, totalPages }) => (
  <BodyPage
    parity={parity}
    pageNumber={pageNumber}
    totalPages={totalPages}
    sectionLabel="HOW"
    sectionColor={SECTION_INK["02_HOW"]}
    eyebrow={HOW.cascade.eyebrow}
    headline={HOW.cascade.headline}
  >
    <p
      style={{
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 17,
        lineHeight: 1.35,
        color: COLORS.INK_MUTED,
        margin: "0 0 20px",
        maxWidth: "6.4in",
      }}
    >
      {HOW.cascade.lede}
    </p>

    <div style={{ display: "grid", gridTemplateColumns: "3.5in 1fr", columnGap: 26, alignItems: "start" }}>
      <LayerCascade />

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <p
          style={{
            fontFamily: FONTS.SANS,
            fontSize: TYPE.body.size,
            lineHeight: TYPE.body.lh,
            letterSpacing: TYPE.body.tracking,
            color: COLORS.INK,
            margin: 0,
          }}
        >
          {HOW.cascade.body}
        </p>

        <div
          style={{
            borderTop: `1pt solid ${COLORS.INK}`,
            paddingTop: 12,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: COLORS.INK_MUTED,
            }}
          >
            The rule of the cascade
          </span>
          <p
            style={{
              fontFamily: FONTS.SERIF,
              fontStyle: "italic",
              fontSize: 15,
              lineHeight: 1.4,
              color: COLORS.INK,
              margin: 0,
            }}
          >
            A layer only runs when the one above it was not sure enough to file.
            Cheap and certain first; expensive and learned last; a human beyond
            that.
          </p>
        </div>
      </div>
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{HOW.cascade.source}</SourceNote>
    </div>
  </BodyPage>
);
