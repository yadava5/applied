import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

/** One captured frame: a file under the frames public dir, and the second it
 *  was painted at, measured from the first frame of the take. */
export interface CapturedFrame {
  file: string;
  t: number;
}

export interface SceneMeta {
  id: string;
  title: string;
  url: string;
  capturedAt: string;
  viewport: { width: number; height: number };
  /** Device pixels per CSS pixel in the captured PNGs. */
  scale: number;
  /** The window on the page, in CSS px. */
  crop: { x: number; y: number; width: number; height: number };
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
 * that moves is the product moving.
 */
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
  // It has to finish one frame BEFORE `total`, not at it. The last frame a
  // composition renders is `durationInFrames - 1`, so a dissolve ending at
  // `total` never reaches 1 — it stops at 1 - (1/fps)/fade, which is 90% at
  // 30fps over 0.35s, and the clip loops out of a half-dissolved frame. The
  // verify gate measured that as a 0.6% seam on two of the three clips.
  const total = holdIn + playFor + holdOut + fade;
  const fadeIn = fade > 0
    ? interpolate(t, [total - fade, total - 1 / fps], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  // CSS px -> composition px. The crop rectangle is expressed in CSS pixels and
  // the PNGs are `scale` times that, so one factor covers both.
  const k = width / scene.crop.width;
  const sheet: React.CSSProperties = {
    position: "absolute",
    left: -scene.crop.x * k,
    top: -scene.crop.y * k,
    width: scene.viewport.width * k,
    height: scene.viewport.height * k,
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f1011", overflow: "hidden", width, height }}>
      <Img src={staticFile(`${scene.id}/${current.file}`)} style={sheet} />
      {fadeIn > 0 ? (
        <Img src={staticFile(`${scene.id}/${first.file}`)} style={{ ...sheet, opacity: fadeIn }} />
      ) : null}
    </AbsoluteFill>
  );
};
