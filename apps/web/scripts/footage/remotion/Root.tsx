import React from "react";
import { Composition, continueRender, delayRender, staticFile } from "remotion";

import { Clip, type ClipProps, type SceneMeta } from "./Clip";
import { OauthClip, oauthDuration, type Shot } from "./OauthClip";

/**
 * The hand-captured clip: the owner's own screen recording of connecting a real
 * Gmail account. It is the one artifact on the page we do not own — Google's
 * consent screen is not ours to redraw, and reproducing it in DOM would be
 * inventing an artifact and attributing it to a real company.
 *
 * Times are seconds into `oauth-raw.mov`; crops are in that file's own pixels
 * (3024x1898, a 2x capture of a 1512pt screen). All three crops are the same
 * size, so the three beats cut together without the frame resizing.
 *
 * WHAT IS CUT, AND WHY — every one of these is a whole segment removed, never a
 * frame altered:
 *   · 3.3–15.3s  the account chooser and the redirect. Dead time, and the
 *                chooser carries a second personal Google account.
 *   · 9–14.5s    (inside that span) Google's "hasn't verified this app"
 *                interstitial. Cut at the owner's explicit instruction: the
 *                page states the verification status plainly in its Access copy,
 *                and the warning is temporary state rather than a property of
 *                the product. NOTE: the consent screen itself carries its own
 *                embedded "hasn't been verified" panel, and that panel is
 *                simply ABOVE this shot's crop — it has not been painted over.
 *   · 17.6s on   the return, the Settings scroll, and then the owner's real
 *                dashboard: 42 filed applications with real employer names.
 *                The clip ends on the connection card, not on the board.
 */
const OAUTH_SHOTS: Shot[] = [
  {
    label: "the connection card, before",
    from: 1.4,
    to: 3.4,
    crop: { x: 974, y: 161, width: 1044, height: 240 },
  },
  {
    label: "the one permission Google is asked for",
    from: 15.4,
    to: 17.6,
    crop: { x: 1542, y: 595, width: 1044, height: 240 },
  },
  {
    label: "the same card, after",
    from: 26.6,
    to: 28.8,
    crop: { x: 974, y: 212, width: 1044, height: 240 },
  },
];

const OAUTH = {
  id: "gmail-connects",
  fade: 0.35,
  holdOut: 0.7,
  source: { width: 3024, height: 1898 },
  shots: OAUTH_SHOTS,
};

/**
 * The cut. One entry per scene: which slice of the take to keep, and how long
 * to hold either end.
 *
 * These are the only editorial numbers in the pipeline, and they are here
 * rather than in the capture so that re-cutting a clip does not mean
 * re-recording the app. `window` is in CAPTURE seconds — read them off
 * `scene.json`, or off a contact sheet.
 */
const CUTS: Record<string, Omit<ClipProps, "scene">> = {
  // Rest, one press of Sync, the whole strip lands at ~2.4s. Everything after
  // 2.9s in the take is the same frame, so the take is cut there and the
  // stillness is bought back as a deliberate hold on the result.
  "board-syncs": { window: { from: 0, to: 2.9 }, holdIn: 0.5, holdOut: 1.1, fade: 0.4 },
  // The body streams in over ~3.5s and the verdict lands at 90% at the end.
  // A shorter hold in, because the opening frame is an empty field and there is
  // nothing to read in it.
  "rules-read-the-body": { window: { from: 0, to: 3.8 }, holdIn: 0.3, holdOut: 0.6, fade: 0.3 },
  // The press of "Try a sample export" lands at ~0.75s of the take and the
  // counters are there in the next paint — `ingest()` is synchronous, because
  // nothing leaves the tab. So the cut is: a beat on the un-run page, the
  // arrival, then a long hold on the arithmetic, which is what there is to
  // read. `scenes.mjs` argues why an instantaneous change is the honest shape
  // for this claim rather than a shortcoming to hide.
  "import-classifies": { window: { from: 0.1, to: 2.6 }, holdIn: 0.4, holdOut: 0.8, fade: 0.35 },
};

/**
 * Encoded width, in px. The encode is sized for where it is SHOWN, not for
 * where it was captured — and where these are shown moved.
 *
 * It was 832: twice the 26rem artifact column the clips were first placed in.
 * That column is gone; the placements are 768 CSS px wide, so on the 2x screen
 * this page is designed on, an 832px encode was covering 1536 device px — 54%
 * of native, which is exactly the softness that reads as "not premium" and
 * cannot be fixed anywhere downstream of here.
 *
 * 1152 is the ceiling the CAPTURE supports rather than a round number: the
 * scenes crop at or under 576 CSS px and record at `--force-device-scale-factor=2`,
 * so 1152 is their native device-pixel width and `Clip.tsx`'s
 * `k = width / scene.crop.width` lands on exactly 2.0 — one downscale of 1.0,
 * i.e. none. Nothing here scales a frame UP, and raising this further would.
 * At 768 CSS on a 2x screen that is 75% of native instead of 54%.
 *
 * The one scene that crops wider (`import-classifies`, 720 CSS px for the
 * stats row's four cells) is still a genuine downscale at 1152: 0.8x.
 */
const OUT_WIDTH = 1152;

const FPS = 30;

/** Even numbers only — H.264 will not encode odd dimensions. */
const even = (n: number) => Math.round(n / 2) * 2;

export const SCENE_IDS = Object.keys(CUTS);
export const OAUTH_ID = OAUTH.id;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id={OAUTH.id}
        component={OauthClip}
        fps={FPS}
        width={OUT_WIDTH}
        height={even((OUT_WIDTH * OAUTH_SHOTS[0].crop.height) / OAUTH_SHOTS[0].crop.width)}
        durationInFrames={Math.round(oauthDuration(OAUTH_SHOTS, OAUTH.fade, OAUTH.holdOut) * FPS)}
        defaultProps={{
          // Served out of the same public dir the captured frames use, so the
          // render step has one asset root. The file itself is NOT committed:
          // it is 11 MB of screen recording and there is nowhere honest to put
          // it in the repo.
          src: "oauth/oauth-raw.mov",
          source: OAUTH.source,
          shots: OAUTH_SHOTS,
          fade: OAUTH.fade,
          holdOut: OAUTH.holdOut,
        }}
        calculateMetadata={({ props }) => ({
          props: { ...props, src: staticFile(props.src) },
        })}
      />
      {SCENE_IDS.map((id) => {
        const cut = CUTS[id];
        return (
          <Composition
            key={id}
            id={id}
            component={Clip}
            fps={FPS}
            // Real values arrive from calculateMetadata; these only have to be
            // legal so the composition can be registered.
            width={OUT_WIDTH}
            height={468}
            durationInFrames={FPS}
            defaultProps={{ ...cut, scene: undefined as unknown as SceneMeta }}
            calculateMetadata={async () => {
              // The capture writes `scene.json` beside its frames; the clip's
              // size and duration are DERIVED from it rather than restated
              // here, so a re-capture at a different crop cannot silently
              // produce a stretched clip.
              const handle = delayRender(`scene.json for ${id}`);
              const scene: SceneMeta = await fetch(staticFile(`${id}/scene.json`)).then((r) => r.json());
              continueRender(handle);
              const seconds = cut.holdIn + (cut.window.to - cut.window.from) + cut.holdOut + cut.fade;
              return {
                props: { ...cut, scene },
                width: OUT_WIDTH,
                height: even((OUT_WIDTH * scene.crop.height) / scene.crop.width),
                durationInFrames: Math.round(seconds * FPS),
              };
            }}
          />
        );
      })}
    </>
  );
};
