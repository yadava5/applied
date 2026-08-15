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
