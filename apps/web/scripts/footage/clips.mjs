import { SCENES } from "./scenes.mjs";

/**
 * The clip that is NOT captured by `capture.mjs`.
 *
 * Connecting a Gmail account needs a real Google account and a real consent
 * screen, so this one was recorded by hand off the deployed app. Its source is
 * `oauth/oauth-raw.mov` under the frames directory, it is 11 MB, and it is not
 * committed — see `scripts/footage/README.md` for what re-recording it takes.
 */
export const HAND_CAPTURED = {
  id: "gmail-connects",
  source: "oauth/oauth-raw.mov",
};

/** Every clip under `public/footage/`, in the order the page argues them. */
export const CLIPS = [HAND_CAPTURED.id, ...SCENES.map((s) => s.id)];

/**
 * Which frame each poster is taken from, in seconds into the COMPOSED clip.
 *
 * It used to be frame 0 for every clip, which is the loop's own "before" by
 * construction — and that is the wrong still for every placement these clips
 * actually have. The poster is what a reduced-motion visitor, a data-saver
 * visitor and anyone who scrolls past without playing sees INSTEAD of the
 * recording, so it is the frame that has to carry the argument on its own.
 * Frame 0 of `rules-read-the-body` is an empty field under `OTHER 50%` and the
 * line "below 0.90 — the full pipeline would defer to e5 / SetFit": the
 * product not having done the thing, stated twice.
 *
 * Each of these is inside its clip's held END state — after the take has
 * landed and before the loop dissolve starts — so the still is a real frame of
 * the real recording and the visitor who does play it watches the product
 * arrive at the picture they were already shown.
 *
 * Seconds, not frame numbers, because the cut's holds are written in seconds
 * (`remotion/Root.tsx`); `render.mjs` multiplies by the composition's own fps.
 */
export const POSTER_AT = {
  "board-syncs": 3.6,
  "rules-read-the-body": 4.3,
  "import-classifies": 3.0,
};
