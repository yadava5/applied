import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/** One captured frame: a file under the frames public dir, and the second it
 *  was painted at, measured from the first frame of the take. */
export interface CapturedFrame {
  file: string;
  t: number;
}

/** Where the frame sits over the page at one moment of capture time. */
export interface CameraKey {
  at: number;
  x: number;
  y: number;
}

/**
 * A camera: one frame size, and the positions it holds and travels between.
 * See `scenes.mjs` for why the size never changes — the short version is that
 * a zoom would have to scale captured pixels up, and this pipeline does not.
 */
export interface Camera {
  width: number;
  height: number;
  path: CameraKey[];
}

export interface SceneMeta {
  id: string;
  title: string;
  url: string;
  capturedAt: string;
  viewport: { width: number; height: number };
  /** Device pixels per CSS pixel in the captured PNGs. */
  scale: number;
  /** The window on the page, in CSS px. For a tracked scene this is the
   *  BOUNDING BOX of the camera's travel — what the capture's `forbid` gate
   *  is measured against — and `camera` is what actually gets rendered. */
  crop: { x: number; y: number; width: number; height: number };
  /** Present only on tracked scenes. */
  camera?: Camera;
  frames: CapturedFrame[];
}

/**
 * A `type` alias, not an `interface`, and that is load-bearing: Remotion's
 * `<Composition>` constrains its props to `Record<string, unknown>`, and an
 * interface has no implicit index signature so it does not satisfy that.
 */
export type ClipProps = {
  scene: SceneMeta;
  /** Seconds of the take to keep, measured in capture time. */
  window: { from: number; to: number };
  /** Seconds of held first frame before the take starts playing. */
  holdIn: number;
  /** Seconds of held last frame after it ends. */
  holdOut: number;
  /** Seconds of crossfade from the held last frame back to the first, so the
   *  loop closes without a cut. */
  fade: number;
};

/**
 * The nearest captured frame at or before a moment in capture time. The
 * screencast emits a frame when the compositor paints one, so gaps between
 * timestamps are real stillness: holding the previous frame across a gap is
 * what the page actually looked like, and interpolating between them would
 * invent motion that never happened.
 */
function frameAt(frames: CapturedFrame[], t: number): CapturedFrame {
  let lo = 0;
  let hi = frames.length - 1;
  if (t <= frames[0].t) return frames[0];
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (frames[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  return frames[lo];
}

/**
 * The frame's rectangle at a moment in capture time.
 *
 * Eased per segment, not across the whole path: a hold is two keys at the same
 * position, so easing it is a no-op, and the move between two keys gets the
 * whole in-and-out curve to itself. A linear pan is the tell of a camera that
 * is not being operated — it starts and stops as if hit.
 */
function rectAt(camera: Camera, t: number) {
  const { path, width, height } = camera;
  const at = (k: CameraKey) => k.at;
  if (t <= at(path[0])) return { ...path[0], width, height };
  const last = path[path.length - 1];
  if (t >= at(last)) return { ...last, width, height };
  const i = path.findIndex((k, j) => j > 0 && t <= at(k));
  const a = path[i - 1];
  const b = path[i];
  const ease = { easing: Easing.inOut(Easing.cubic), extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
  return {
    x: interpolate(t, [a.at, b.at], [a.x, b.x], ease),
    y: interpolate(t, [a.at, b.at], [a.y, b.y], ease),
    width,
    height,
  };
}

/**
 * A clip: the captured frames, cropped to the scene's window, re-timed onto a
 * held-open / play / held-closed arc, and cross-dissolved back to its own first
 * frame so it loops without a seam.
 *
 * The composition is sized to the DISPLAY size the landing gives it, and the
 * source is larger than that — the crop is 1.3-1.4x the card's CSS width and
 * was captured at 2x on top of that. The browser downsamples once, at render
 * time, into the encode. Nothing here scales a frame UP.
 *
 * There are no graphics over the footage and no synthetic cursor. Every pixel
 * that moves is the product moving; where the frame is, and when it moves, is
 * the camera's, and the README's covenant says which is which.
 */

/**
 * Frames of settled first-frame at the very end, after the dissolve has
 * finished — the loop point rendered SEVERAL times rather than once.
 *
 * One was enough while every clip was a stationary window: the dissolve's two
 * ends were the same rectangle, so an encoder arriving at the last frame had
 * almost no residual to carry. A tracked clip dissolves between two camera
 * POSITIONS, which is a much larger change to encode, and VP9 lands on the
 * final frame still 0.14% away from it — a real, visible seam, caught by
 * `verify.mjs` and not by anything in the render. Three identical frames give
 * the encoder somewhere to converge, and cost 50ms of a hold that was already
 * a hold.
 */
const LOOP_SETTLE = 3;
export const Clip: React.FC<ClipProps> = ({ scene, window: win, holdIn, holdOut, fade }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;

  const playFor = win.to - win.from;
  // The take plays at 1x inside its hold sandwich; past the end it freezes.
  const captureTime = win.from + Math.min(playFor, Math.max(0, t - holdIn));
  const current = frameAt(scene.frames, captureTime);
  const first = scene.frames[0];

  // The dissolve runs over the last `fade` seconds, taking the frozen closing
  // frame back to the opening one, so the loop point is two identical frames
  // and the seam is gone rather than hidden.
  //
  // It has to finish BEFORE `total`, not at it. The last frame a composition
  // renders is `durationInFrames - 1`, so a dissolve ending at `total` never
  // reaches 1 — it stops at 1 - (1/fps)/fade, which is 90% at 30fps over
  // 0.35s, and the clip loops out of a half-dissolved frame. The verify gate
  // measured that as a 0.6% seam on two of the three clips. It now finishes
  // `LOOP_SETTLE` frames early instead of one, for the encoder's sake as much
  // as the arithmetic's.
  const total = holdIn + playFor + holdOut + fade;
  const fadeIn = fade > 0
    ? interpolate(t, [total - fade, total - LOOP_SETTLE / fps], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  // CSS px -> composition px. The frame is expressed in CSS pixels and the PNGs
  // are `scale` times that, so one factor covers both.
  const frameAtCapture = (at: number) =>
    scene.camera ? rectAt(scene.camera, at) : scene.crop;
  const k = width / (scene.camera?.width ?? scene.crop.width);
  const sheet = (rect: { x: number; y: number }): React.CSSProperties => ({
    position: "absolute",
    left: -rect.x * k,
    top: -rect.y * k,
    width: scene.viewport.width * k,
    height: scene.viewport.height * k,
  });

  // The dissolve joins the take's last moment to its first. On a TRACKED clip
  // that is two camera positions as well as two moments, so each layer carries
  // its own rectangle — the outgoing one frozen where the camera came to rest,
  // the incoming one back where it started. The README's covenant says this
  // out loud: a loop seam is a join, not a claim that the shot ran both ways.
  return (
    <AbsoluteFill style={{ backgroundColor: "#0f1011", overflow: "hidden", width, height }}>
      <Img src={staticFile(`${scene.id}/${current.file}`)} style={sheet(frameAtCapture(captureTime))} />
      {fadeIn > 0 ? (
        <Img
          src={staticFile(`${scene.id}/${first.file}`)}
          // `first.t`, not `win.from`: the rectangle has to belong to the
          // IMAGE being dissolved to, which is the take's first captured
          // frame. Matching the window's start instead would put the camera a
          // few tenths away from the picture on any clip whose cut opens late,
          // and the loop seam would come back as a slide.
          style={{ ...sheet(frameAtCapture(first.t)), opacity: fadeIn }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
