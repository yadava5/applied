"use client";

import { toast } from "sonner";

import {
  Countdown,
  FeedbackChannel,
  renderToast,
  type FeedbackEvent,
} from "@/lib/feedback/coalesce";
import { ToastCard } from "./ToastCard";

/**
 * The executor for `lib/feedback/coalesce.ts` — the ONLY module that calls
 * sonner's `toast()`. Call sites go through `notifySuccess` / `notifyError` /
 * `notifyUndo`, never sonner directly, because sonner has no idea two events
 * are the same action: the dedupe, the silent-action refusal and the
 * no-timer-for-errors rule all live in the channel, and a direct `toast()`
 * call would walk straight past them.
 *
 * Timers are owned HERE, not by sonner: every sonner toast is created with
 * `duration: Infinity` and dismissed by our own `Countdown`-driven timeout.
 * That is not re-implementation for its own sake — sonner 2.0.8 pauses its
 * timers on hover (and on its expand hotkey) but NOT when a toast's button
 * merely receives keyboard focus, and #511's undo guarantee hangs on exactly
 * that pause. `FeedbackToaster` reports hover/focus over the stack via
 * `setTimersPaused`, and the pause applies to every open countdown at once,
 * matching sonner's own hover behaviour (the hovered stack expands as one).
 */

const channel = new FeedbackChannel();
const timers = new Map<string, { countdown: Countdown; handle: number | null }>();
let stackHeld = false;

/** The toast left the screen — release the dedupe bucket and the timer. */
function finalize(id: string) {
  channel.resolve(id);
  const timer = timers.get(id);
  if (timer?.handle != null) clearTimeout(timer.handle);
  timers.delete(id);
}

function closeToast(id: string) {
  toast.dismiss(id);
  finalize(id);
}

function schedule(id: string) {
  const timer = timers.get(id);
  if (!timer) return;
  if (timer.handle != null) {
    clearTimeout(timer.handle);
    timer.handle = null;
  }
  if (timer.countdown.isPaused) return;
  timer.handle = window.setTimeout(() => closeToast(id), timer.countdown.remainingAt(Date.now()));
}

/** Hover or focus anywhere over the stack holds every countdown; leaving
 *  resumes them where they stopped. Called by `FeedbackToaster` only. */
export function setTimersPaused(paused: boolean) {
  if (paused === stackHeld) return;
  stackHeld = paused;
  const now = Date.now();
  for (const [id, timer] of timers) {
    if (paused) {
      timer.countdown.pause(now);
      if (timer.handle != null) {
        clearTimeout(timer.handle);
        timer.handle = null;
      }
    } else {
      timer.countdown.resume(now);
      schedule(id);
    }
  }
}

function emit(event: FeedbackEvent, action?: { label: string; run: () => void }) {
  const decision = channel.decide(event);
  if (decision.action === "suppress") return;
  const active = decision.toast;

  if (active.duration !== null) {
    const existing = timers.get(active.id);
    // A merged occurrence refills the window (see `Countdown.reset`); a new
    // toast starts one, already held if the pointer is on the stack.
    if (existing) existing.countdown.reset(Date.now());
    else timers.set(active.id, {
      countdown: new Countdown(active.duration, Date.now(), stackHeld),
      handle: null,
    });
    schedule(active.id);
  }

  const { text, countBadge } = renderToast(active);
  toast.custom(
    () => (
      <ToastCard
        kind={active.kind}
        text={text}
        countBadge={countBadge}
        actionLabel={action?.label}
        onAction={
          action
            ? () => {
                action.run();
                closeToast(active.id);
              }
            : undefined
        }
        onDismiss={() => closeToast(active.id)}
      />
    ),
    // Same id on an "update" decision = sonner swaps the content in place
    // (one toast, count climbing) instead of stacking a sibling. Duration is
    // Infinity always — dismissal is ours (see the module note).
    { id: active.id, duration: Infinity, onDismiss: () => finalize(active.id) },
  );
}

/** A server side-effect with no other surface succeeded. `countMessage` is
 *  what a rapid burst reads as — "5 applications updated". */
export function notifySuccess(
  key: string,
  message: string,
  opts?: { countMessage?: (count: number) => string },
) {
  emit({ key, kind: "success", message, countMessage: opts?.countMessage });
}

/** A mutation failed somewhere with no inline error of its own. Holds until
 *  dismissed — `DURATIONS.error` is null and stays null. */
export function notifyError(key: string, message: string) {
  emit({ key, kind: "error", message });
}

/**
 * A recoverable action landed and the toast carries its way back. `run` must
 * actually restore the thing (e.g. `restoreApplication`) — this affordance is
 * never rendered decoratively. The key MUST name the target
 * (`application.dismiss.42`): distinct targets must not merge, because one
 * Undo button cannot restore two rows.
 */
export function notifyUndo(
  key: string,
  message: string,
  undo: { label?: string; run: () => void | Promise<void> },
) {
  emit({ key, kind: "undo", message }, { label: undo.label ?? "Undo", run: () => void undo.run() });
}
