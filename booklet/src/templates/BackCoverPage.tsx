import React from "react";
import { QRCodeSVG } from "qrcode.react";
import { COLORS, FONTS } from "../theme";
import { BACK_COVER } from "../content";
import { CoverField } from "../visuals/CoverField";

/**
 * Back cover (page 28). Continues the front cover's envelope field (reseeded
 * so it reads as a wraparound), then lands the reader on the live product: a
 * QR to the web app on a paper card, plus the in-browser classifier Space.
 */
export const BackCoverPage: React.FC = () => (
  <section
    className="page"
    data-bleed="true"
    style={{
      background: COLORS.GROUND,
      color: COLORS.ON_DARK,
      position: "relative",
      overflow: "hidden",
    }}
  >
    <CoverField widthIn={8.75} heightIn={11.25} variant="back" />

    {/* Colophon — upper-left */}
    <div
      style={{
        position: "absolute",
        top: "0.7in",
        left: "0.7in",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 500,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: COLORS.ON_DARK_MUTED,
        lineHeight: 1.6,
      }}
    >
      {BACK_COVER.colophon.map((line, i) => (
        <React.Fragment key={i}>
          {line}
          <br />
        </React.Fragment>
      ))}
    </div>

    {/* QR block — center-lower, on a paper card for scannability */}
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: "2.2in",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 14,
      }}
    >
      <div
        style={{
          background: COLORS.PAPER,
          borderRadius: 12,
          padding: 18,
          boxShadow: `0 0 0 1px ${COLORS.ON_DARK_HAIRLINE}`,
        }}
      >
        <QRCodeSVG value={BACK_COVER.qrTarget} size={150} level="M" marginSize={0} fgColor={COLORS.GROUND} />
      </div>
      <div
        style={{
          fontFamily: FONTS.MONO,
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: COLORS.ON_DARK,
        }}
      >
        {BACK_COVER.qrCaption}
      </div>
      <div
        style={{
          fontFamily: FONTS.SANS,
          fontSize: 15,
          fontWeight: 600,
          letterSpacing: "-0.01em",
          color: COLORS.RULES_CYAN,
        }}
      >
        {BACK_COVER.qrTarget.replace("https://", "")}
      </div>
    </div>

    {/* In-browser classifier Space note */}
    <div
      style={{
        position: "absolute",
        left: "0.9in",
        right: "0.9in",
        bottom: "1.35in",
        textAlign: "center",
        fontFamily: FONTS.MONO,
        fontSize: 8.5,
        fontWeight: 500,
        letterSpacing: "0.04em",
        color: COLORS.ON_DARK_MUTED,
        lineHeight: 1.5,
      }}
    >
      {BACK_COVER.spaceNote}
    </div>

    {/* Closing italic line — bottom-right */}
    <div
      style={{
        position: "absolute",
        bottom: "0.7in",
        right: "0.7in",
        fontFamily: FONTS.SERIF,
        fontStyle: "italic",
        fontSize: 14,
        color: COLORS.ON_DARK_MUTED,
        textAlign: "right",
      }}
    >
      {BACK_COVER.closingLine}
    </div>
  </section>
);
