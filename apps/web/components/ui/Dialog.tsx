"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * A minimal, dependency-free modal dialog: focus is moved in on open and
 * restored to the trigger on close, Tab is trapped inside the panel, Escape
 * and backdrop clicks dismiss, and body scroll is locked while open. Rendered
 * as a fixed overlay (no portal) so it composes cleanly inside the app shell.
 *
 * Motion is CSS-only (`.dialog-*` in globals.css) and collapses to a static
 * state under prefers-reduced-motion.
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

  if (!open) return null;

  const overlayClass =
    variant === "sheet"
      ? "dialog-overlay fixed inset-0 z-[100] flex justify-end bg-background/70 backdrop-blur-sm"
      : "dialog-overlay fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-background/70 p-4 backdrop-blur-sm sm:items-center sm:p-6";
  const panelClass =
    variant === "sheet"
      ? // The sheet owns its scroll: the page behind is scroll-locked while it
        // is open, so this is the only scroll context on screen.
        `sheet-panel relative h-dvh w-full max-w-xl overflow-y-auto border-l border-line-strong bg-surface p-5 shadow-[0_0_80px_-24px_rgba(0,0,0,0.85)] outline-none sm:p-6 ${className}`.trim()
      : `dialog-panel relative my-auto w-full max-w-lg rounded-2xl border border-line-strong bg-surface p-5 shadow-[0_30px_80px_-24px_rgba(0,0,0,0.85)] outline-none sm:p-6 ${className}`.trim();

  return (
    <div
      className={overlayClass}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={panelClass}
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
      </div>
    </div>
  );
}
