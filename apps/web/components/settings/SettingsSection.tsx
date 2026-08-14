"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

/**
 * One Settings card: a consistent titled surface every section composes into,
 * so spacing, borders, and heading rhythm never drift between sections.
 */
export function SettingsSection({
  title,
  description,
  id,
  children,
  tone = "default",
}: {
  title: string;
  description?: ReactNode;
  id?: string;
  children: ReactNode;
  tone?: "default" | "danger";
}) {
  return (
    // `scroll-mt-16` below `lg` clears the chip strip SettingsNav pins to the
    // top of the scroll pane (53px tall) — without it an anchor jump lands the
    // heading underneath it. At `lg` the rail sits beside the cards with
    // nothing above them, so the jump only needs room to breathe.
    <section
      id={id}
      aria-label={title}
      className={`scroll-mt-16 rounded-xl border bg-surface p-5 lg:scroll-mt-4 ${
        tone === "danger" ? "border-reject/30" : "border-line-soft"
      }`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-medium text-strong">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** A labelled read-only value row (email, member-since, sign-in method). */
export function ReadonlyField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid gap-1">
      <span className="label-caps">{label}</span>
      <span className="text-sm text-muted">{value}</span>
    </div>
  );
}

/** How long a success line stays on screen before removing itself (#213). */
export const STATUS_LINGER_MS = 4000;

/**
 * True while `active` is — but only for `ms` after each rise. The mechanism
 * behind every transient success line on this page: #213 was "Saved" and
 * "Password updated" sitting for the life of the mount, asserting an event
 * minutes after it happened. A success is an event, so it clears itself; an
 * unresolved ERROR is a current fact and is deliberately not routed through
 * this — it stays until the user acts on it (retype, retry, cancel).
 */
export function useLinger(active: boolean, ms = STATUS_LINGER_MS): boolean {
  const [expired, setExpired] = useState(false);
  // Render-time reset on the `active` edge (the React "adjust state when a
  // prop changes" pattern) — the effect below only ever sets state from the
  // timer callback, never synchronously inside the effect body.
  const [prevActive, setPrevActive] = useState(active);
  if (active !== prevActive) {
    setPrevActive(active);
    setExpired(false);
  }
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => setExpired(true), ms);
    return () => window.clearTimeout(timer);
  }, [active, ms]);
  return active && !expired;
}

/**
 * A status line that enters with a small settle and fades out when it goes —
 * so a clearing "Saved" reads as designed rather than as a glitch. Instant
 * under reduced motion, and the content is never gated on the animation.
 */
export function TransientStatus({
  show,
  className = "",
  children,
}: {
  show: boolean;
  className?: string;
  children: ReactNode;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <AnimatePresence>
      {show ? (
        <motion.span
          role="status"
          className={`text-xs ${className}`.trim()}
          initial={reduceMotion ? false : { opacity: 0, y: 2 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0 }}
          transition={{ duration: 0.15, ease: "easeOut" }}
        >
          {children}
        </motion.span>
      ) : null}
    </AnimatePresence>
  );
}

/** A tiny inline save-status line shared by the client sections. */
export function SaveStatus({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  // "saved" lingers then clears itself; "saving"/"error" show as long as the
  // parent's state says so (the parents already reset to idle on new input).
  const settled = useLinger(state === "saved");
  const map = {
    saving: { text: "Saving…", cls: "text-dim" },
    saved: { text: "Saved", cls: "text-live" },
    error: { text: "Couldn’t save — try again.", cls: "text-reject-ink" },
  } as const;
  const entry = state === "idle" ? null : map[state];
  const show = entry !== null && (state !== "saved" || settled);
  return (
    <TransientStatus show={show} className={entry?.cls}>
      {entry?.text}
    </TransientStatus>
  );
}
