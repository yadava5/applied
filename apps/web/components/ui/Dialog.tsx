"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * A minimal modal dialog: focus is moved in on open and restored to the
 * trigger on close, Tab is trapped inside the panel, Escape and backdrop
 * clicks dismiss, and body scroll is locked while open. Rendered as a fixed
 * overlay (no portal) so it composes cleanly inside the app shell.
 *
 * Motion runs through the motion library (`AnimatePresence`) so the panel has
 * a real exit as well as an entrance — the scrim fades, the centre panel
 * rises, the sheet slides from the right edge. Fast by design (a tool opened
 * twenty times a day), and `useReducedMotion` collapses every transition to
 * instant: the content itself is never gated on an animation.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className = "",
  variant = "center",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /**
   * `center` — the classic modal. `sheet` — a full-height panel pinned to the
   * right edge (the application detail view); same focus trap, Escape,
   * backdrop and scroll lock, different geometry and entrance.
   */
  variant?: "center" | "sheet";
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!open) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";

    // Move focus to the first FIELD if the dialog has a form, else the first
    // focusable control (e.g. the close button on a content-only dialog).
    const panel = panelRef.current;
    const firstField = panel?.querySelector<HTMLElement>("input, textarea, select");
    const firstFocusable = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (firstField ?? firstFocusable ?? panel)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (focusable.length === 0) return;
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      previouslyFocused?.focus?.();
    };
  }, [open, onClose]);

  const overlayClass =
    variant === "sheet"
      ? "fixed inset-0 z-[100] flex justify-end bg-background/70 backdrop-blur-sm"
      : "fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-background/70 p-4 backdrop-blur-sm sm:items-center sm:p-6";
  const panelClass =
    variant === "sheet"
      ? // The sheet owns its scroll: the page behind is scroll-locked while it
        // is open, so this is the only scroll context on screen.
        `relative h-dvh w-full max-w-xl overflow-y-auto border-l border-line-strong bg-surface p-5 shadow-[0_0_80px_-24px_rgba(0,0,0,0.85)] outline-none sm:p-6 ${className}`.trim()
      : `relative my-auto w-full max-w-lg rounded-2xl border border-line-strong bg-surface p-5 shadow-[0_30px_80px_-24px_rgba(0,0,0,0.85)] outline-none sm:p-6 ${className}`.trim();

  // Enter/exit for each geometry. Exits are quicker than entrances — closing
  // must never feel like waiting.
  const panelMotion = reduceMotion
    ? {
        initial: false as const,
        animate: { opacity: 1 },
        exit: { opacity: 1, transition: { duration: 0 } },
      }
    : variant === "sheet"
      ? {
          initial: { opacity: 0, x: 24 },
          animate: { opacity: 1, x: 0 },
          exit: { opacity: 0, x: 16 },
        }
      : {
          initial: { opacity: 0, y: 8, scale: 0.985 },
          animate: { opacity: 1, y: 0, scale: 1 },
          exit: { opacity: 0, y: 6, scale: 0.99 },
        };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className={overlayClass}
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduceMotion ? { opacity: 1, transition: { duration: 0 } } : { opacity: 0 }}
          transition={{ duration: 0.15, ease: "easeOut" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            className={panelClass}
            {...panelMotion}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 id={titleId} className="text-lg font-medium text-strong">
                  {title}
                </h2>
                {description ? (
                  <p id={descId} className="mt-1 text-sm text-muted">
                    {description}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close dialog"
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            {children}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
