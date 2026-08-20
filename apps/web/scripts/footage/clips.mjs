import { SCENES } from "./scenes.mjs";

/**
 * The clip that is NOT captured by `capture.mjs`.
 *
 * Connecting a Gmail account needs a real Google account and a real consent
 * screen, so this one was recorded by hand off the deployed app. Its source is
 * `oauth/oauth-raw.mov` under the frames directory, it is 11 MB, and it is not
 * committed — see `scripts/footage/README.md` for what re-recording it takes.
 *
 * HELD OUT OF `CLIPS`, AND THEREFORE OUT OF `public/footage/`, since
 * 2026-08-19. The recording is the best privacy exhibit in the repository —
 * Google's own consent screen stating the single permission — and that same
 * screen names `jobtracker-api-seven.vercel.app`, the host from before the
 * JobTracker → Applied rename, so on a page selling Applied it reads as
 * consent granted to a different product (copy.ts argues why cropping the
 * host line out would be worse). Nothing referenced the encoded files —
 * `components/marketing/footage.ts` never listed the id — so ~430 KB shipped
 * on every deploy for no frame anyone could reach. The definition stays so
 * the clip can come back the day it is honest: rename the Google Cloud OAuth
 * client, re-record the consent flow by hand off the deployed app, then put
 * `HAND_CAPTURED.id` back at the head of `CLIPS`.
 */
export const HAND_CAPTURED = {
  id: "gmail-connects",
  source: "oauth/oauth-raw.mov",
};

/**
 * RETIRED, and not held: `import-classifies`, removed 2026-08-20.
 *
 * The difference from `HAND_CAPTURED` above is the whole point of writing
 * this down. That one is HELD — the recording is good and the blocker is a
 * hostname, so its definition stays and a docblock says what letting it back
 * in takes. This one was rejected on what it SHOWS, by the owner, twice: the
 * first take pressed "Try a sample export" and showed no process at all, and
 * the re-staged drag take never showed a file being chosen and ran past too
 * fast to read. There is no re-cut of the captured frames that fixes either,
 * so keeping the scene would be keeping a recipe for a take that was already
 * refused.
 *
 * It is therefore gone from `scenes.mjs`, `remotion/Root.tsx`, `POSTER_AT`,
 * `public/footage/`, `components/marketing/footage.ts` and `copy.ts`. The
 * capture choreography — the synthetic drop of a real `File` built from
 * `SAMPLE_MBOX`, and the derived crop that survives an ingest-and-reload —
 * is worth reading if the import path is ever recorded again, and it is at
 * `1de1a54:apps/web/scripts/footage/scenes.mjs`.
 *
 * The access phase carries the ask without an exhibit now, rather than with
 * one of the other two recordings moved into the hole — `AccessPhase` argues
 * that, and it is a real cost of this removal, not a neutral one.
 */
export const RETIRED = ["import-classifies"];

/** Every clip under `public/footage/`, in the order the page argues them.
 *  `HAND_CAPTURED.id` belongs at its head once re-recorded — see above. */
export const CLIPS = [...SCENES.map((s) => s.id)];

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
  // The seated row, and the reason a TRACKED clip needs this map even more
  // than a stationary one does: frame 0 of `one-letter` is the letter, so a
  // first-frame poster would show a reduced-motion visitor a piece of mail
  // and no board at all — the setup, with the entire payoff withheld. The
  // camera comes to rest at 5.05s of composed time (0.2 of held-in plus the
  // path's last move, which lands at 4.85 of capture time) and holds until
  // 6.8, where the loop dissolve starts. 6.0 is inside that hold with room
  // either side.
  "one-letter": 6.0,
  // 10.2, moved from 4.3 when the take was retimed to per-keystroke typing
  // (5.0s -> 10.9s, 2026-08-19): 4.3s of the NEW clip is mid-word under
  // OTHER 50% — exactly the "before" frame this map exists to avoid. 10.2
  // sits inside the held end state: full body, REJECTION 90%, the accept-bar
  // line — after the landing at ~9.9 and before the loop dissolve at ~10.6.
  "rules-read-the-body": 10.2,
};
