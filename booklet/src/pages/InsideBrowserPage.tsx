import React from "react";
import { BodyPage } from "../templates/BodyPage";
import { COLORS, FONTS, TYPE, SECTION_INK } from "../theme";
import { INSIDE, BRAND } from "../content";
import { DeviceCard } from "../primitives/DeviceCard";
import { SourceNote } from "../primitives/SourceNote";

/** Page 17 — the model runs in the browser, zero servers. */
export const InsideBrowserPage: React.FC<{
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
    eyebrow={INSIDE.browser.eyebrow}
    headline={INSIDE.browser.headline}
  >
    <div style={{ display: "grid", gridTemplateColumns: "1fr 2.9in", columnGap: 26, alignItems: "start" }}>
      <div style={{ maxWidth: "3.6in" }}>
        {INSIDE.browser.body.map((p, i) => (
          <p
            key={i}
            style={{
              fontFamily: FONTS.SANS,
              fontSize: TYPE.body.size,
              lineHeight: TYPE.body.lh,
              letterSpacing: TYPE.body.tracking,
              color: COLORS.INK,
              margin: "0 0 10px",
            }}
          >
            {p}
          </p>
        ))}
      </div>

      {/* Device panel — the classifier running client-side */}
      <DeviceCard chrome={`${BRAND.liveUrl}/demo`} accent={COLORS.E5_VIOLET}>
        <div style={{ fontFamily: FONTS.MONO, fontSize: 9, lineHeight: 1.7, color: COLORS.ON_DARK_MUTED }}>
          <div style={{ color: COLORS.ON_DARK_SUBTLE }}>{"// no backend · WASM"}</div>
          <div>
            <span style={{ color: COLORS.E5_VIOLET }}>load</span> model_quantized.onnx
          </div>
          <div style={{ color: COLORS.ON_DARK_SUBTLE }}>&nbsp;&nbsp;22.8 MB · int8 · cached</div>
          <div style={{ marginTop: 6 }}>
            <span style={{ color: COLORS.SETFIT_GREEN }}>classify</span>(email)
          </div>
          <div style={{ color: COLORS.ON_DARK_SUBTLE }}>&nbsp;&nbsp;→ interview · 0.88</div>
          <div style={{ marginTop: 6, color: COLORS.RULES_CYAN }}>◍ runs on your CPU</div>
        </div>
      </DeviceCard>
    </div>

    {/* Facts grid */}
    <div
      style={{
        marginTop: 26,
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 0,
        border: `0.5pt solid ${COLORS.HAIRLINE}`,
        borderRadius: 5,
        overflow: "hidden",
      }}
    >
      {INSIDE.browser.facts.map((f, i) => (
        <div
          key={f.k}
          style={{
            padding: "11px 14px",
            borderTop: i >= 2 ? `0.5pt solid ${COLORS.HAIRLINE}` : "none",
            borderLeft: i % 2 === 1 ? `0.5pt solid ${COLORS.HAIRLINE}` : "none",
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.MONO,
              fontSize: 8.5,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: SECTION_INK["03_INSIDE"],
            }}
          >
            {f.k}
          </span>
          <span style={{ fontFamily: FONTS.SANS, fontSize: 11, fontWeight: 500, color: COLORS.INK }}>
            {f.v}
          </span>
        </div>
      ))}
    </div>

    {/* Parity — honestly framed */}
    <div
      style={{
        marginTop: 22,
        display: "flex",
        gap: 16,
        alignItems: "flex-start",
        borderLeft: `2.5px solid ${COLORS.SETFIT_GREEN}`,
        paddingLeft: 14,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 30,
          fontWeight: 700,
          color: COLORS.SETFIT_DEEP,
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
        }}
      >
        {INSIDE.browser.parity.claim}
      </div>
      <div>
        <div style={{ fontFamily: FONTS.SANS, fontSize: 12, fontWeight: 600, color: COLORS.INK, marginBottom: 3 }}>
          {INSIDE.browser.parity.label}
        </div>
        <div style={{ fontFamily: FONTS.SERIF, fontStyle: "italic", fontSize: 11.5, lineHeight: 1.4, color: COLORS.INK_MUTED }}>
          {INSIDE.browser.parity.honest}
        </div>
      </div>
    </div>

    <div style={{ position: "absolute", left: "0.75in", bottom: "1.1in" }}>
      <SourceNote>{INSIDE.browser.source}</SourceNote>
    </div>
  </BodyPage>
);
