import React from "react";
import { COLORS, FONTS, TYPE, PAGE } from "../theme";
import { Page } from "../primitives/Page";
import { Eyebrow } from "../primitives/Eyebrow";

/**
 * Flexible body-page template — the workhorse for narrative content,
 * diagrams, and hero-stat pages. Sub-components render directly inside
 * `children`; the template handles the eyebrow / headline chrome AND the
 * page's vertical rhythm.
 *
 * VERTICAL RHYTHM: the in-flow content (eyebrow + headline + children) is
 * balanced inside the live area with two weighted flex spacers rather than
 * top-anchored, so a short page reads as an intentional composition instead
 * of content stranded above a band of dead space. The spacers `minHeight: 0`
 * + `flex-shrink`, so a page whose content is *taller* than the live area
 * simply pushes the spacers to zero and flows from the top — it never clips.
 *
 * Anchoring is preserved: this wrapper stays `position: static`, so any
 * absolutely-positioned child a page supplies (e.g. a bottom `SourceNote`
 * rail) still resolves against the `.page` box and holds its position, as
 * does the page-number footer. This lift is generic — copy it into every
 * booklet that inherits this framework.
 */
export type BodyPageProps = {
  parity: "recto" | "verso";
  pageNumber: number;
  totalPages: number;
  sectionLabel: string;
  sectionColor: string;
  eyebrow?: string;
  headline?: string;
  headlineSize?: keyof typeof TYPE;
  /** Vertical placement of the in-flow content. Default balances it. */
  align?: "top" | "center";
  children: React.ReactNode;
};

/** Live area = trim height minus the top/bottom content margins. */
const LIVE_HEIGHT = `calc(${PAGE.trimH}in - ${PAGE.margin.top}in - ${PAGE.margin.bottom}in)`;

export const BodyPage: React.FC<BodyPageProps> = ({
  parity,
  pageNumber,
  totalPages,
  sectionLabel,
  sectionColor,
  eyebrow,
  headline,
  headlineSize = "h1",
  align = "center",
  children,
}) => {
  const h = TYPE[headlineSize] as typeof TYPE.h1;
  // Slight top bias so the headline sits a touch above dead-center — reads
  // more composed than a perfectly centered block.
  const topGrow = align === "center" ? 0.82 : 0;
  const bottomGrow = align === "center" ? 1.18 : 1;
  return (
    <Page
      parity={parity}
      pageNumber={pageNumber}
      totalPages={totalPages}
      sectionLabel={sectionLabel}
      sectionColor={sectionColor}
    >
      <div style={{ display: "flex", flexDirection: "column", minHeight: LIVE_HEIGHT }}>
        <div aria-hidden style={{ flexGrow: topGrow, flexShrink: 1, flexBasis: 0, minHeight: 0 }} />
        <div>
          {eyebrow && (
            <Eyebrow color={sectionColor} style={{ marginBottom: 10 }}>
              {eyebrow}
            </Eyebrow>
          )}
          {headline && (
            <h1
              style={{
                fontFamily: FONTS.SANS,
                fontSize: h.size,
                fontWeight: h.weight,
                letterSpacing: h.tracking,
                lineHeight: h.lh,
                color: COLORS.INK,
                margin: "0 0 14px",
              }}
            >
              {headline}
            </h1>
          )}
          {children}
        </div>
        <div aria-hidden style={{ flexGrow: bottomGrow, flexShrink: 1, flexBasis: 0, minHeight: 0 }} />
      </div>
    </Page>
  );
};
