"use client";

import { useRef } from "react";
import { Toaster as SonnerToaster } from "sonner";

import { MAX_VISIBLE } from "@/lib/feedback/coalesce";
import { setTimersPaused } from "./notify";
import "./toaster.css";

/**
 * THE toaster — mounted exactly once, in `app/(app)/layout.tsx` (#511 rule 1).
 * Sonner supplies the stack, the swipe handling and the polite live region;
 * the cards themselves are `ToastCard`, so nothing of sonner's default look
 * survives.
 *
 * The wrapper div is the pause instrument. Countdowns belong to `notify.tsx`,
 * and they hold while the pointer OR keyboard focus is anywhere over the
 * stack — sonner's own pause covers hover only, and the undo button's
 * keyboard guarantee needs the focus half (see notify.tsx). The blur handler
 * checks `relatedTarget` so tabbing BETWEEN two toasts never lets the timers
 * slip through the gap.
 */
export function FeedbackToaster() {
  const hovered = useRef(false);
  const focused = useRef(false);
  const sync = () => setTimersPaused(hovered.current || focused.current);

  return (
    <div
      onMouseEnter={() => {
        hovered.current = true;
        sync();
      }}
      onMouseLeave={() => {
        hovered.current = false;
        sync();
      }}
      onFocusCapture={() => {
        focused.current = true;
        sync();
      }}
      onBlurCapture={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        focused.current = false;
        sync();
      }}
    >
      <SonnerToaster position="bottom-right" visibleToasts={MAX_VISIBLE} gap={10} />
    </div>
  );
}
