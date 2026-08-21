/**
 * The shipped recordings, by id and intrinsic size — read from
 * `public/footage/manifest.json`, which `scripts/footage/render.mjs` writes
 * with the real byte counts and dimensions of what it encoded.
 *
 * A PLAIN MODULE, not part of `ProductClip.tsx`, and that is not tidying. The
 * clip map used to live in the component, which carries `"use client"`; a
 * server component that imports a value across that boundary gets a client
 * REFERENCE rather than the object, so a clip arrived as `undefined` and the
 * page 500'd on `clip.id` at render. Data that both sides of the boundary
 * read has to sit outside it.
 *
 * The sizes are here so the box can be reserved before a byte of video lands:
 * the layout cannot move when it does.
 */
export const CLIPS = {
  rulesReadTheBody: { id: "rules-read-the-body", width: 1152, height: 630 },
  boardSyncs: { id: "board-syncs", width: 1152, height: 310 },
  // 4:3 since the 2026-08-21 re-capture — the owner's big-box direction for
  // the row rail ("covers the entire half of the left side"). The frame is
  // 704x528 CSS captured at 2x, so 1408x1056 is the encode's native pixel
  // grid: at the row rail's 44rem ceiling the picture renders 702 CSS px
  // wide and a 2x screen reads it at essentially 1:1.
  oneLetter: { id: "one-letter", width: 1408, height: 1056 },
} as const;

export type Clip = (typeof CLIPS)[keyof typeof CLIPS];
