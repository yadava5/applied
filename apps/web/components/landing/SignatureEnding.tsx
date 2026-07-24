"use client";

import { useEffect, useRef, useState } from "react";
import { ScrambleText } from "./ScrambleText";

/**
 * The signature ending — Applied's own, no borrowed motif.
 *
 * One envelope descends the lane, and as it crosses each classifier layer the
 * band it passes pulses in that layer's hue (cyan rules → violet e5 → green
 * SetFit). It clears the 0.85 gate, then collapses into a single green verdict
 * glyph — the ring draws, the check lands, a ripple breathes out — while the
 * `applied` wordmark decodes in beneath it. It plays once when scrolled
 * into view, and can be replayed.
 *
 * Reduced-motion renders the resolved end state directly (verdict glyph formed,
 * wordmark set), with no envelope and no motion.
 */

function Scene({ run, reduced }: { run: number; reduced: boolean }) {
  // Scene is keyed by `run` in the parent, so each play remounts it and `landed`
  // resets to its initial value — no manual reset needed. When reduced, the
  // wordmark is forced resolved via the `active` prop below, independent of this.
  const [landed, setLanded] = useState(false);

  useEffect(() => {
    if (reduced || run === 0) return;
    const id = setTimeout(() => setLanded(true), 2000);
    return () => clearTimeout(id);
  }, [run, reduced]);

  const cls = reduced ? "sig sig--static" : run > 0 ? "sig sig--play" : "sig";

  return (
    <div className={cls}>
      <svg
        viewBox="0 0 480 330"
        className="sig__svg mx-auto block w-full max-w-[420px]"
        role="img"
        aria-label="An email descends through the three classifier layers, clears the 0.85 gate, and resolves into a single verdict."
      >
        {/* lane guide */}
        <line
          x1="240"
          y1="30"
          x2="240"
          y2="292"
          stroke="var(--line-soft)"
          strokeWidth="1"
          strokeDasharray="2 6"
        />

        {/* layer bands */}
        {[
          { y: 116, color: "var(--viz-rules)", n: "1", label: "rules" },
          { y: 160, color: "var(--viz-embeddings)", n: "2", label: "e5" },
          { y: 204, color: "var(--viz-setfit)", n: "3", label: "SetFit" },
        ].map((b, i) => (
          <g key={b.label} className="sig__band" style={{ color: b.color, ["--d" as string]: `${0.55 + i * 0.35}s` }}>
            <line x1="170" y1={b.y} x2="290" y2={b.y} stroke="currentColor" strokeWidth="1.5" />
            <text x="300" y={b.y + 3.5} fontSize="9.5" fill="currentColor" className="font-mono">
              {b.n} · {b.label}
            </text>
          </g>
        ))}

        {/* gate */}
        <g className="sig__band sig__gate" style={{ color: "var(--amber)", ["--d" as string]: "1.6s" }}>
          <line
            x1="160"
            y1="248"
            x2="300"
            y2="248"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="5 4"
          />
          <text x="308" y="251.5" fontSize="9.5" fill="currentColor" className="font-mono">
            0.85 · gate
          </text>
        </g>

        {/* verdict node */}
        <g style={{ color: "var(--viz-setfit)" }}>
          <circle className="sig__glow" cx="240" cy="290" r="30" fill="currentColor" />
          <circle className="sig__ripple" cx="240" cy="290" r="21" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle className="sig__ring" cx="240" cy="290" r="21" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <path
            className="sig__check"
            d="M231 290 L237.5 297 L251 281"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        {/* the descending envelope */}
        <g transform="translate(240 44)">
          <g className="sig__envelope" style={{ color: "var(--text-muted)" }}>
            <rect x="-26" y="-16" width="52" height="32" rx="3.5" fill="var(--surface)" stroke="currentColor" strokeWidth="1.4" />
            <path d="M-26 -14 L0 3 L26 -14" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </g>
        </g>
      </svg>

      {/* wordmark + caption */}
      <div className="sig__mark mt-6 text-center">
        <p className="font-mono text-2xl font-semibold text-strong sm:text-3xl">
          <ScrambleText text="applied" mode="scramble" active={reduced ? true : landed} perCharMs={42} />
        </p>
        <p className="mt-3 font-mono text-[11px] text-dim">
          one email · three layers · one gate · one verdict
        </p>
      </div>
    </div>
  );
}

export function SignatureEnding() {
  const ref = useRef<HTMLDivElement>(null);
  const [run, setRun] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const el = ref.current;
    const isReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Deferred a frame so it's never a synchronous effect setState.
    const raf = requestAnimationFrame(() => setReduced(isReduced));
    if (isReduced || !el || typeof IntersectionObserver === "undefined") {
      return () => cancelAnimationFrame(raf);
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setRun((r) => (r === 0 ? 1 : r));
            io.disconnect();
            break;
          }
        }
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, []);

  return (
    <div ref={ref} className="relative">
      {/* keyed so a replay cleanly restarts every CSS animation in the scene */}
      <Scene key={run} run={run} reduced={reduced} />

      {!reduced && (
        <div className="mt-6 flex justify-center">
          <button
            type="button"
            onClick={() => setRun((r) => r + 1)}
            className="spring-ease rounded-lg border border-line px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-widest text-muted hover:border-line-strong hover:text-strong"
          >
            ↺ replay
          </button>
        </div>
      )}
    </div>
  );
}
