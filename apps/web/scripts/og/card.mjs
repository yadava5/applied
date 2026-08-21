/**
 * The composition of `public/og.png`, as one HTML document.
 *
 * THIS FILE HOLDS NO PROSE, and that is structural rather than tidy. Every
 * word drawn into the card arrives as an argument, from
 * `components/marketing/copy.ts`, which `tests/unit/landing-voice.test.mjs`
 * scans for dashes and for internals. A sentence typed in here would be drawn
 * into a PNG that no gate in this repo can read. See the `OG` block in
 * copy.ts for the full argument and for the alt text that shipped describing
 * a different picture entirely.
 *
 * THE MARK IS `app/icon.svg`, redrawn at card scale. It keeps its own two
 * hexes (#06B6D4, #10B981) rather than the landing tokens, because the point
 * of putting it here is that it is recognisably the same mark sitting in the
 * reader's tab. Everything else takes its colour from `app/globals.css`.
 *
 * THE COMPOSITION IS THE MARK'S OWN READING, drawn once at card scale: the
 * mark is a row that moved, so the card gives it the board to move on. Three
 * full-bleed hairlines cross the card at exactly the heights of the mark's
 * three node centres — computed from the same viewBox fractions, not eyeballed
 * — so the enlarged mark reads as one application climbing lanes, the filled
 * green node at rest on the top lane. The headline sets the landing's two-beat
 * reversal typographically: the loss in the dim weight, the cause in the
 * heaviest weight the face carries. One figure, one sentence; the foot's two
 * privacy claims stay small and quiet beneath them.
 */

/** From `app/globals.css`. Copied, not imported, because this document is
 *  rendered by Playwright outside the Next build and cannot read the app's
 *  stylesheet. Six values; drift here is visible in the render. */
const TOKEN = {
  background: "#0a0a0b",
  textStrong: "#f7f8f8",
  textDim: "#aeb4be",
  line: "rgb(255 255 255 / 0.09)",
  /** `--green` from globals.css: the accent for the lane the row landed on. */
  green: "#4ade80",
  markRing: "#06B6D4",
  markFill: "#10B981",
};

export const CARD = { width: 1200, height: 630 };

/** The family name the render script also asserts against, so a silent
 *  fallback to a system face cannot ship. */
export const FONT_FAMILY = "Atkinson Hyperlegible Next";

/** The mark's box on the card. The lanes below are derived from this, so the
 *  figure and the structure cannot drift apart. */
const MARK = { size: 400, top: 40, right: 28 };

/** `app/icon.svg` node geometry in its own viewBox (4..44): the three circle
 *  centres the lanes must pass through, lowest first. */
const NODE_CY = [33.5, 24, 14.5];

export function cardHtml(words, fontDataUri) {
  /** The headline's two beats, split on the sentence boundary the copy already
   *  carries — reweighted, never reworded. A single-sentence line renders
   *  whole in the strong beat. */
  const beats = words.line.split(/(?<=\.)\s+/);
  const beatA = beats.length > 1 ? beats.slice(0, -1).join(" ") : "";
  const beatB = beats[beats.length - 1];

  /** Lane y for a node centre: same fraction of the mark's box the node
   *  occupies in the viewBox, offset by where the box sits on the card. */
  const laneY = (cy) => MARK.top + ((cy - 4) / 40) * MARK.size;
  const lanes = NODE_CY.map(
    (cy) => `<div class="lane" style="top: ${laneY(cy)}px"></div>`,
  ).join("\n  ");

  /** The top lane is the one the filled node rests on: it carries a green
   *  trail from the left edge to the node's centre, brightest at the node and
   *  fading back the way the row came. Same fractions as the mark, so the
   *  trail meets the node exactly. */
  const markLeft = CARD.width - MARK.right - MARK.size;
  const litNodeX = markLeft + ((34.5 - 4) / 40) * MARK.size;
  const litLaneY = laneY(NODE_CY[NODE_CY.length - 1]);

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>
  @font-face {
    font-family: "${FONT_FAMILY}";
    src: url("${fontDataUri}") format("woff2");
    font-weight: 200 800;
    font-style: normal;
    font-display: block;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: ${CARD.width}px; height: ${CARD.height}px;
    background: ${TOKEN.background};
    font-family: "${FONT_FAMILY}";
    -webkit-font-smoothing: antialiased;
  }
  .card {
    width: 100%; height: 100%;
    position: relative; overflow: hidden;
  }
  .lane { position: absolute; left: 0; right: 0; height: 1px; background: ${TOKEN.line}; }
  .lane-lit {
    position: absolute; left: 0; height: 2px; margin-top: -1px;
    background: linear-gradient(to left, ${TOKEN.green}e6, ${TOKEN.green}00 88%);
    box-shadow: 0 0 18px 1px ${TOKEN.green}26;
  }
  .mark { position: absolute; top: ${MARK.top}px; right: ${MARK.right}px; }
  .wordmark {
    position: absolute; left: 80px; top: 58px;
    font-size: 30px; font-weight: 700; letter-spacing: -0.01em;
    color: ${TOKEN.textStrong};
  }
  .line { position: absolute; left: 80px; top: 356px; }
  .beat {
    display: block; letter-spacing: -0.025em; white-space: nowrap;
  }
  .beat-a {
    font-size: 74px; font-weight: 350; line-height: 1.08;
    color: ${TOKEN.textDim};
  }
  .beat-b {
    font-size: 90px; font-weight: 800; line-height: 1.1;
    color: ${TOKEN.textStrong};
  }
  .foot {
    position: absolute; left: 80px; bottom: 44px;
    font-size: 23px; font-weight: 400; color: ${TOKEN.textDim};
  }
</style></head>
<body><div class="card">
  ${lanes}
  <div class="lane-lit" style="top: ${litLaneY}px; width: ${litNodeX}px"></div>
  <div class="mark">${markSvg(MARK.size)}</div>
  <span class="wordmark">${escapeHtml(words.wordmark)}</span>
  <h1 class="line">
    ${beatA ? `<span class="beat beat-a">${escapeHtml(beatA)}</span>` : ""}
    <span class="beat beat-b">${escapeHtml(beatB)}</span>
  </h1>
  <p class="foot">${escapeHtml(words.foot)}</p>
</div></body></html>`;
}

/** `app/icon.svg` without its container rect, at an arbitrary box size. */
function markSvg(size) {
  return `<svg width="${size}" height="${size}" viewBox="4 4 40 40" aria-hidden="true">
  <g stroke-linecap="round">
    <path d="M17.2,30.2 L20.3,27.4" stroke="${TOKEN.textStrong}" stroke-opacity="0.65" stroke-width="2"/>
    <path d="M27.7,20.7 L30.6,18.1" stroke="${TOKEN.textStrong}" stroke-opacity="0.65" stroke-width="2"/>
    <circle cx="13.5" cy="33.5" r="3" fill="none" stroke="${TOKEN.markRing}" stroke-width="2.4"/>
    <circle cx="24" cy="24" r="3" fill="none" stroke="${TOKEN.markRing}" stroke-width="2.4"/>
    <circle cx="34.5" cy="14.5" r="4.1" fill="${TOKEN.markFill}"/>
  </g>
</svg>`;
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
