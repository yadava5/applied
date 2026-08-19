"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { FOOTAGE } from "./copy";

/**
 * A recording of the running product, played at the beat that argues for it.
 *
 * The page's other exhibits are the app itself — a live board, a live
 * classification. These cannot be: each shows a surface being USED, and a page
 * cannot demonstrate use. So they are footage, and they are labelled as
 * footage (`FOOTAGE.label`), because the board embed calls itself "not a
 * video" (`BOARD.live`) and that distinction is worth more than the five
 * seconds it costs to protect.
 *
 * THE FRAME IS THE PAGE'S OWN. A clip used to sit on this page as a bare
 * rounded rectangle with a caption under it — a video dropped into a document.
 * It wears the window act's specimen frame now: the same `rounded-2xl border
 * border-line`, the same chrome strip with a mark on the left and one control
 * on the right, the same shadow. What differs is exactly one glyph, and it is
 * the honest one — the live board's mark is a filled dot, present tense, and
 * this one is a hollow ring: the same instrument, pointed at something that
 * already happened. The strip's own bottom rule doubles as the playback
 * track, so the clip's position in its loop is legible without adding a
 * control surface to read it off.
 *
 * IT LOOPS, and that is what the whole treatment turns on. A five-second
 * recording that plays once and freezes on its last frame is a thing the
 * reader has to catch; a loop is a thing they can watch. The control is
 * therefore Play/Pause, not "Replay" — the action the reader actually has.
 *
 * MECHANISM. Two IntersectionObservers, and they do different jobs:
 *
 *   · ARM, at a viewport's margin, flips `preload` to `auto`. `preload="none"`
 *     is right for a page with three recordings on it — a slow connection
 *     spends nothing on a clip nobody has scrolled near — but it also means
 *     the FIRST play is a cold fetch, and a clip that stutters into its first
 *     second is the whole of "not smooth". Arming a viewport early buys the
 *     bytes before they are needed and still spends nothing on a visitor who
 *     never gets there.
 *   · PLAY, over the same centre band the two acts use, starts it when it is
 *     the thing being read and pauses it when it is not. Nothing moves
 *     off-screen and no two clips can ever run at once.
 *
 * Restarting on re-entry is deliberate: the clip's argument is an arc, and a
 * reader returning to it should get the arc rather than whatever phase the
 * loop happens to be in.
 *
 * WHAT A VISITOR GETS ON THE WORST PATH. Until the bytes land the poster is
 * the whole exhibit, and the posters are the clips' LANDED END STATES rather
 * than their first frames (scripts/footage/clips.mjs argues it) — the still
 * has to make the product's case on its own, and a loop's first frame is its
 * "before" by construction. Reduced motion never autoplays — matched at the
 * moment of the decision rather than at mount, since that is the only reading
 * guaranteed to be current — but the control stays, so the recording is
 * offered rather than withheld. Autoplay can also be refused outright by the
 * browser, or the tab can be backgrounded; both land in the same place, and
 * the control is what the reader does about it.
 */

/** Intrinsic size, from public/footage/manifest.json — the box is reserved
 *  from these so the layout cannot move when the bytes land. */
export const CLIPS = {
  rulesReadTheBody: { id: "rules-read-the-body", width: 1152, height: 630 },
  importClassifies: { id: "import-classifies", width: 1152, height: 840 },
  boardSyncs: { id: "board-syncs", width: 1152, height: 310 },
} as const;

type Clip = (typeof CLIPS)[keyof typeof CLIPS];

/** How far outside the viewport a clip starts fetching, as a share of it. One
 *  viewport is roughly one deliberate scroll gesture at these page lengths. */
const ARM_MARGIN = "100% 0px";

/** The band a clip has to be inside to be "the thing being read". */
const PLAY_BAND = "-25% 0px -25% 0px";

export function ProductClip({
  clip,
  name,
  caption,
  className,
}: {
  clip: Clip;
  /** What the recording shows, for anyone who cannot see it. */
  name: string;
  caption: string;
  className?: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const trackRef = useRef<HTMLSpanElement>(null);
  const [playing, setPlaying] = useState(false);

  /** Start from the top, muted, and never throw at it. `currentTime` is a
   *  no-op before the metadata is in, so on a cold element the rewind waits
   *  for it rather than being silently dropped. */
  const play = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = true; // belt and braces: an audible clip is refused autoplay
    const rewind = () => {
      video.currentTime = 0;
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) rewind();
    else video.addEventListener("loadedmetadata", rewind, { once: true });
    video.play().then(
      () => setPlaying(true),
      // Refused: by the autoplay policy, by a backgrounded tab, or because the
      // reader asked for reduced motion. The poster stays, the control stays,
      // and the label is already the right one.
      () => setPlaying(false),
    );
  }, []);

  const pause = useCallback(() => {
    videoRef.current?.pause();
    setPlaying(false);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || typeof IntersectionObserver === "undefined") return;

    const arm = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        video.preload = "auto";
        arm.disconnect();
      },
      { rootMargin: ARM_MARGIN, threshold: 0 },
    );
    arm.observe(video);

    // Kept in a ref rather than state: the visibility handler reads it, and
    // "is this on screen" is not a reason to render.
    let inBand = false;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          inBand = entry.isIntersecting;
          if (!inBand) {
            pause();
            continue;
          }
          if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) continue;
          play();
        }
      },
      { rootMargin: PLAY_BAND, threshold: 0 },
    );
    io.observe(video);

    // A backgrounded tab pauses media and does not resume it. Without this a
    // reader who switches away and back finds the exhibit stopped, which is
    // the same defect as a clip that never started.
    const onVisible = () => {
      if (document.visibilityState !== "visible" || !inBand) return;
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      play();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      arm.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [play, pause]);

  /**
   * The playback track, written per frame rather than off `timeupdate` —
   * `timeupdate` fires about four times a second, and a progress rule that
   * advances in visible steps looks broken in a way a still one does not. One
   * `scaleX` write per frame, and only while it is actually running.
   */
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const video = videoRef.current;
      const track = trackRef.current;
      if (video && track && video.duration > 0) {
        track.style.transform = `scaleX(${video.currentTime / video.duration})`;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  return (
    <figure
      className={cn(
        // The caption rides beside the frame from `xl`, where the container is
        // wide enough to hold both: the frame is capped at the width its
        // encode is sharp at, and a 768px frame alone in a 1152px container is
        // the dead right-hand column this page has already had to fix twice.
        // Below `xl` there is no room for a second column and it sits under
        // the frame, which is where a caption goes.
        "grid gap-x-10 gap-y-3 xl:grid-cols-[minmax(0,48rem)_minmax(0,1fr)] xl:items-start",
        className,
      )}
    >
      <div className="overflow-clip rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-2 sm:px-5">
          <span className="label-caps flex items-center gap-2">
            {/* hollow, where the live board's is filled: same instrument,
                pointed at something that already happened */}
            <span
              aria-hidden
              className="h-1.5 w-1.5 rounded-full border border-current opacity-70"
            />
            {FOOTAGE.label}
          </span>
          <button
            type="button"
            onClick={playing ? pause : play}
            // `py-1.5` is the target, not the look: the label is 11px of caps
            // and a pointer needs more than that to land on.
            className="label-caps shrink-0 py-1.5 transition-colors hover:text-strong"
          >
            {playing ? FOOTAGE.pause : FOOTAGE.play}
          </button>
        </div>
        <div className="relative bg-background">
          {/* The chrome strip's own rule, filling. It is the only thing on the
              frame that is not the recording, and it says one true machine
              thing: where this loop is. */}
          <span aria-hidden className="absolute inset-x-0 top-0 z-10 h-[2px]">
            <span
              ref={trackRef}
              className="block h-full origin-left bg-viz-rules"
              style={{ transform: "scaleX(0)" }}
            />
          </span>
          <video
            ref={videoRef}
            aria-label={name}
            poster={`/footage/${clip.id}.jpg`}
            preload="none"
            muted
            loop
            playsInline
            width={clip.width}
            height={clip.height}
            className="block h-auto w-full"
            style={{ aspectRatio: `${clip.width} / ${clip.height}` }}
          >
            <source src={`/footage/${clip.id}.webm`} type="video/webm" />
            <source src={`/footage/${clip.id}.mp4`} type="video/mp4" />
          </video>
        </div>
      </div>
      <figcaption className="text-[0.8125rem] leading-relaxed text-muted xl:pt-1">
        {caption}
      </figcaption>
    </figure>
  );
}
