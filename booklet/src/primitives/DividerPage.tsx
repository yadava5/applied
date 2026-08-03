import React from "react";
import { COLORS, FONTS, TYPE, PAGE, type SectionKey } from "../theme";
import { DIORAMAS } from "../visuals/diorama";

/**
 * Full-bleed chapter divider. JobTracker's identity inverts the sibling
 * AutoML book: instead of a bright solid-color field, the ground is the
 * near-black app ink (#0B1220) and the chapter's semantic accent carries the
 * giant numeral, the counter, and the diorama's single highlight. The
 * chapter title stays paper-white italic serif for contrast.
 */

export type DividerPageProps = {
  chapterNum: string;
  chapterTitle: string;
  subtitle: string;
  color: string;
  sectionKey: SectionKey;
  chapterIndex: number;
  chapterTotal: number;
};

export const DividerPage: React.FC<DividerPageProps> = ({
  chapterNum,
  chapterTitle,
  subtitle,
  color,
  sectionKey,
  chapterIndex,
  chapterTotal,
}) => {
  const Diorama = DIORAMAS[sectionKey];
  return (
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
      {/* faint dotted grid texture */}
      <GroundGrid />

      {/* Chapter number — massive, top-left, in the section accent. */}
      <div
        style={{
          position: "absolute",
          top: `${PAGE.margin.top}in`,
          left: `${PAGE.margin.outer}in`,
          fontFamily: FONTS.SANS,
          fontSize: TYPE.display.size,
          fontWeight: TYPE.display.weight,
          letterSpacing: TYPE.display.tracking,
          lineHeight: TYPE.display.lh,
          color,
        }}
      >
        {chapterNum}
      </div>

      {/* Chapter title — serif italic, paper-white, just below the numeral. */}
      <div
        style={{
          position: "absolute",
          top: `calc(${PAGE.margin.top}in + ${TYPE.display.size * TYPE.display.lh}pt - 22pt)`,
          left: `${PAGE.margin.outer}in`,
          fontFamily: FONTS.SERIF,
          fontStyle: "italic",
          fontSize: TYPE.sectionTitle.size,
          fontWeight: TYPE.sectionTitle.weight,
          letterSpacing: TYPE.sectionTitle.tracking,
          lineHeight: TYPE.sectionTitle.lh,
          color: COLORS.ON_DARK,
        }}
      >
        {chapterTitle}
      </div>

      {/* Subtitle — serif, dimmed white, two lines max. */}
      <div
        style={{
          position: "absolute",
          top: `calc(${PAGE.margin.top}in + ${TYPE.display.size * TYPE.display.lh}pt + ${TYPE.sectionTitle.size}pt)`,
          left: `${PAGE.margin.outer}in`,
          right: `${PAGE.margin.outer}in`,
          fontFamily: FONTS.SERIF,
          fontStyle: "normal",
          fontSize: TYPE.dividerSubtitle.size + 2,
          fontWeight: 400,
          letterSpacing: TYPE.dividerSubtitle.tracking,
          lineHeight: TYPE.dividerSubtitle.lh,
          color: COLORS.ON_DARK_MUTED,
          maxWidth: "5.5in",
        }}
      >
        {subtitle}
      </div>

      {/* Diorama — isometric line-art in paper-white + the section accent. */}
      <div
        style={{
          position: "absolute",
          right: `${PAGE.margin.outer}in`,
          bottom: `${PAGE.margin.bottom + 0.05}in`,
          width: "3.375in",
          height: "4.5in",
        }}
      >
        {Diorama ? <Diorama /> : null}
      </div>

      {/* Chapter counter — bottom band. */}
      <div
        style={{
          position: "absolute",
          left: `${PAGE.margin.outer}in`,
          bottom: "0.5in",
          fontFamily: FONTS.MONO,
          fontSize: TYPE.eyebrowLarge.size,
          fontWeight: TYPE.eyebrowLarge.weight,
          letterSpacing: TYPE.eyebrowLarge.tracking,
          textTransform: "uppercase",
          color,
        }}
      >
        {String(chapterIndex).padStart(2, "0")} / {String(chapterTotal).padStart(2, "0")}
      </div>
    </section>
  );
};

/** Faint dotted measurement grid — engineering-drawing texture on the ground. */
const GroundGrid: React.FC = () => (
  <svg
    aria-hidden
    style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
  >
    <defs>
      <pattern id="divider-dots" width="26" height="26" patternUnits="userSpaceOnUse">
        <circle cx="1" cy="1" r="1" fill={COLORS.ON_DARK} opacity={0.05} />
      </pattern>
    </defs>
    <rect width="100%" height="100%" fill="url(#divider-dots)" />
  </svg>
);
