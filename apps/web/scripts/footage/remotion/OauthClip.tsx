import React from "react";
import { AbsoluteFill, Freeze, interpolate, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * A rectangle of the source recording, in SOURCE VIDEO PIXELS. The recording is
 * a 2x macOS screen capture, so these are twice the CSS pixels of the screen
 * that was recorded.
 */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Shot {
  /** What this beat shows. Documentation and nothing else — never drawn. */
  label: string;
  /** Seconds into the source recording. */
  from: number;
  to: number;
  crop: Rect;
}

/** A `type`, not an `interface` — see the note on `ClipProps`. */
export type OauthClipProps = {
  src: string;
  /** Natural size of the source recording, in pixels. */
  source: { width: number; height: number };
  shots: Shot[];
  /** Seconds of cross-dissolve between shots, and on the loop. */
  fade: number;
  /** Seconds the closing frame is held before the loop closes. */
  holdOut: number;
};

/** Where each shot sits on the clip's timeline, in seconds. Shots butt up
 *  against each other and overlap by `fade`, so the join is a dissolve. */
export function layOut(shots: Shot[], fade: number) {
  let cursor = 0;
  const laid = shots.map((shot) => {
    const dur = shot.to - shot.from;
    const at = { shot, start: cursor, dur };
    cursor += dur - fade;
    return at;
  });
  return { laid, end: cursor + fade };
}

export const oauthDuration = (shots: Shot[], fade: number, holdOut: number) =>
  layOut(shots, fade).end + holdOut + fade;

/**
 * The recording, scaled and offset so `crop` fills the frame, playing its own
 * slice at 1x.
 *
 * `trimBefore` is in frames at the COMPOSITION's rate, and the enclosing
 * `Sequence` is what makes local frame 0 line up with `shot.from`.
 */
const ShotView: React.FC<{ shot: Shot; src: string; source: OauthClipProps["source"] }> = ({ shot, src, source }) => {
  const { width, fps } = useVideoConfig();
  const k = width / shot.crop.width;
  return (
    <OffthreadVideo
      src={src}
      trimBefore={Math.round(shot.from * fps)}
      muted
      style={{
        position: "absolute",
        left: -shot.crop.x * k,
        top: -shot.crop.y * k,
        width: source.width * k,
        height: source.height * k,
      }}
    />
  );
};

/**
 * The Gmail connection, as it actually happened.
 *
 * Three beats of one real OAuth round trip: the connection card before, the
 * single permission Google asks for, and the same card after. Everything
 * between them — the account chooser, the redirect, and Google's
 * "hasn't been verified" interstitial — is CUT, whole segments removed.
 * Nothing inside a frame is composited, relabelled or re-timed: what Google's
 * UI says, it says here.
 *
 * This clip is not reproducible by `scripts/footage/capture.mjs`; it needs a
 * human with a Google account. See `scripts/footage/README.md`.
 */
export const OauthClip: React.FC<OauthClipProps> = ({ src, source, shots, fade, holdOut }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const { laid, end } = layOut(shots, fade);
  const total = end + holdOut + fade;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f1011", width, height, overflow: "hidden" }}>
      {laid.map(({ shot, start, dur }, i) => {
        const isLast = i === laid.length - 1;
        const opacity = interpolate(
          t,
          [start - fade, start, start + dur - fade, start + dur],
          [i === 0 ? 1 : 0, 1, 1, isLast ? 1 : 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        );
        if (opacity <= 0.001) return null;
        return (
          <Sequence
            key={shot.label}
            from={Math.round(start * fps)}
            durationInFrames={Math.round((dur + (isLast ? holdOut + fade : 0)) * fps)}
            layout="none"
          >
            <AbsoluteFill style={{ opacity, overflow: "hidden" }}>
              <ShotView shot={shot} src={src} source={source} />
            </AbsoluteFill>
          </Sequence>
        );
      })}

      {/* The loop closes by dissolving the held closing frame back to the
          opening one, so there is no cut at the wrap.

          The dissolve finishes one frame BEFORE `total`: the last frame a
          composition renders is `durationInFrames - 1`, so a dissolve ending at
          `total` stops at 1 - (1/fps)/fade — 90% at 30fps over 0.35s — and the
          clip loops out of a half-dissolved frame. */}
      <Sequence from={Math.round((total - fade) * fps)} layout="none">
        <AbsoluteFill
          style={{
            opacity: interpolate(t, [total - fade, total - 1 / fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            overflow: "hidden",
          }}
        >
          {/* FROZEN on the opening shot's first frame. Without this the
              loop-back overlay keeps PLAYING — over a 0.35s dissolve it walks
              0.35s into shot one, so the clip's last frame is shot one plus a
              third of a second (the cursor has moved) rather than shot one's
              first frame, and the wrap is not seamless. Measured as a 0.144%
              seam against a 0.1% ceiling. */}
          <Freeze frame={0}>
            <ShotView shot={shots[0]} src={src} source={source} />
          </Freeze>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
