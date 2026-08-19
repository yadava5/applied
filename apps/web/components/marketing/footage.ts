/**
 * The shipped recordings, by id and intrinsic size — read from
 * `public/footage/manifest.json`, which `scripts/footage/render.mjs` writes
 * with the real byte counts and dimensions of what it encoded.
 *
 * A PLAIN MODULE, not part of `ProductClip.tsx`, and that is not tidying. The
 * clip map used to live in the component, which carries `"use client"`; a
 * server component that imports a value across that boundary gets a client
 * REFERENCE rather than the object, so `CLIPS.importClassifies` arrived as
 * `undefined` and the page 500'd on `clip.id` at render. Data that both sides
 * of the boundary read has to sit outside it.
 *
 * The sizes are here so the box can be reserved before a byte of video lands:
 * the layout cannot move when it does.
 */
export const CLIPS = {
  rulesReadTheBody: { id: "rules-read-the-body", width: 1152, height: 630 },
  importClassifies: { id: "import-classifies", width: 1152, height: 840 },
  boardSyncs: { id: "board-syncs", width: 1152, height: 310 },
} as const;

export type Clip = (typeof CLIPS)[keyof typeof CLIPS];
