"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { FOOTAGE } from "./copy";

/**
 * A recording of the running product, played at the beat that argues for it.
 *
 * The descent's other exhibits are the app itself — a live board, a live
 * classification. This one cannot be: it shows a surface (the demo page's
 * classifier sandbox) being USED, and a page cannot demonstrate use. So it is
 * footage, and it is labelled as footage (`FOOTAGE.label`), because the board
 * embed two sections down calls itself "not a video" and that distinction is
 * worth more than the five seconds it costs to protect.
 *
 * MECHANISM. One IntersectionObserver over the same centre band the two acts
 * use (`ClaimsDescent`, `WindowAct`): the clip plays when it is the thing
 * being read and pauses when it is not, so nothing moves off-screen and no
 * two clips can ever run at once. Restarting on re-entry is deliberate — a
 * clip holds its last frame when it ends, and resuming mid-way from a frozen
 * end state is how a recording reads as broken.
 *
 * WHAT A VISITOR GETS ON THE WORST PATH. `preload="none"`, so a slow
 * connection spends nothing until the clip is actually on screen; until then
 * the poster is the whole exhibit, and the posters were chosen as frames that
 * state the clip's premise on their own. Reduced motion never autoplays —
 * matched at the moment of the decision rather than at mount, since that is
 * the only reading guaranteed to be current — but the control stays, so the
 * recording is offered rather than withheld. Autoplay can also be refused
 * outright by the browser; that rejection lands in the same place.
 */

/** Intrinsic size, from public/footage/manifest.json — the box is reserved
 *  from these so the layout cannot move when the bytes land. */
export const CLIPS = {
  rulesReadTheBody: { id: "rules-read-the-body", width: 832, height: 454 },
} as const;

type Clip = (typeof CLIPS)[keyof typeof CLIPS];

/** Always from the top: see the docblock. Rejection is silent — the poster is
 *  still on screen and the control still works. */
function start(video: HTMLVideoElement, onPlaying: () => void) {
  video.muted = true; // belt and braces: an audible clip is refused autoplay
  video.currentTime = 0;
  video.play().then(onPlaying, () => {});
}

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
  const [played, setPlayed] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) {
            video.pause();
            continue;
          }
          if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) continue;
          start(video, () => setPlayed(true));
        }
      },
      { rootMargin: "-25% 0px -25% 0px", threshold: 0 },
    );
    io.observe(video);
    return () => io.disconnect();
  }, []);

  return (
    <figure className={cn("max-w-xl", className)}>
      <p className="label-caps mb-2">{FOOTAGE.label}</p>
      <video
        ref={videoRef}
        aria-label={name}
        poster={`/footage/${clip.id}.jpg`}
        preload="none"
        muted
        playsInline
        width={clip.width}
        height={clip.height}
        // The recording is of the app in dark, so on a light page it is a black
        // plate. The shadow is what makes that read as a screen rather than a
        // hole in the layout; in dark it costs nothing, being invisible.
        className="block h-auto w-full rounded-xl border border-line-soft bg-surface shadow-[0_18px_44px_-28px_rgb(0_0_0/0.5)]"
        style={{ aspectRatio: `${clip.width} / ${clip.height}` }}
      >
        <source src={`/footage/${clip.id}.webm`} type="video/webm" />
        <source src={`/footage/${clip.id}.mp4`} type="video/mp4" />
      </video>
      <figcaption className="mt-2 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 text-[0.8125rem] leading-relaxed text-muted">
        <span className="min-w-0 flex-1">{caption}</span>
        <button
          type="button"
          onClick={() => {
            const video = videoRef.current;
            if (video) start(video, () => setPlayed(true));
          }}
          // `py-1.5` is the target, not the look: the label is 11px of caps
          // and a pointer needs more than that to land on.
          className="label-caps shrink-0 py-1.5 transition-colors hover:text-strong"
        >
          {played ? FOOTAGE.replay : FOOTAGE.play}
        </button>
      </figcaption>
    </figure>
  );
}
