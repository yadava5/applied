"use client";

import { MoreHorizontal } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";

import {
  menuKeyIntent,
  rovingIndex,
  rowMenuRegistry,
  triggerKeyIntent,
} from "@/lib/dashboard/rowActions";

export interface RowMenuItem {
  key: string;
  label: string;
  /** Second line under the label — what the action actually does. */
  hint?: string;
  tone?: "default" | "danger";
  onSelect: () => void;
}

/**
 * The row-actions menu — a real menu this time.
 *
 * What was measured on the old inline version, and what each part here answers:
 *
 *   - nothing dismissed it. An outside click on the heading, a bare `mousedown`
 *     on `body`, and a full pointerdown/mousedown/mouseup/click sequence all
 *     left it open; only the trigger's own toggle closed it. → capture-phase
 *     `pointerdown` AND `mousedown` listeners on `document`, both guarded
 *     against the trigger and the menu so the trigger's toggle still wins (an
 *     unguarded outside-close fires on the same interaction that opens the menu
 *     and it never appears at all).
 *   - Escape had no handler anywhere: dispatched `cancelable: true` on the
 *     menu, on `activeElement`, on `document` and on `window` it came back
 *     `defaultPrevented: false` four times out of four. → capture-phase
 *     handlers on `window` and `document` (an event dispatched AT `window` never
 *     travels through `document`, so both are needed) plus the menu's own
 *     handler, each calling `preventDefault`.
 *   - two menus could be open at once. → `rowMenuRegistry`: opening one closes
 *     the other. A stale menu overlapping another row's cards is how the wrong
 *     row's Delete gets clicked.
 *   - the trigger had no `aria-haspopup`, focus never entered the menu, and
 *     ArrowDown did nothing. → `aria-haspopup="menu"` + `aria-controls`, focus
 *     moved to the first item on open, and the WAI-ARIA roving keys
 *     (ArrowDown/Up/Home/End, wrapping) from `rowActions.ts`.
 *
 * Focus returns to the trigger when the user closes the menu themselves
 * (Escape, Tab, toggle) or picks an item — but NOT on an outside click, which
 * would yank focus away from whatever they just clicked.
 */
export function RowActionsMenu({
  label,
  items,
  disabled = false,
  triggerRef: externalTriggerRef,
}: {
  /** Accessible name for the trigger, e.g. `Row actions for Acme`. */
  label: string;
  items: RowMenuItem[];
  disabled?: boolean;
  /** Optional handle so the card can return focus here after its own actions. */
  triggerRef?: RefObject<HTMLButtonElement | null>;
}) {
  const uid = useId();
  const triggerId = `row-actions-trigger-${uid}`;
  const menuId = `row-actions-menu-${uid}`;

  const [open, setOpen] = useState(false);
  const localTriggerRef = useRef<HTMLButtonElement | null>(null);
  const triggerRef = externalTriggerRef ?? localTriggerRef;
  const menuRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeIndex = useRef(0);
  const pendingFocus = useRef<"first" | "last">("first");

  const focusItem = useCallback((index: number) => {
    activeIndex.current = index;
    itemRefs.current[index]?.focus();
  }, []);

  const close = useCallback(
    (returnFocus: boolean) => {
      setOpen(false);
      rowMenuRegistry.close(menuId);
      if (returnFocus) triggerRef.current?.focus();
    },
    [menuId, triggerRef],
  );

  const openMenu = useCallback((focus: "first" | "last") => {
    pendingFocus.current = focus;
    setOpen(true);
  }, []);

  // Release the registry slot if the row disappears with its menu open.
  useEffect(() => () => rowMenuRegistry.close(menuId), [menuId]);

  useEffect(() => {
    if (!open) return;

    rowMenuRegistry.open(menuId, () => setOpen(false));

    const index = pendingFocus.current === "last" ? Math.max(items.length - 1, 0) : 0;
    pendingFocus.current = "first";
    focusItem(index);

    const onOutside = (event: Event) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      close(false);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (menuKeyIntent(event.key) !== "close" || event.key !== "Escape") return;
      event.preventDefault();
      close(true);
    };

    document.addEventListener("pointerdown", onOutside, true);
    document.addEventListener("mousedown", onOutside, true);
    document.addEventListener("keydown", onEscape, true);
    window.addEventListener("keydown", onEscape, true);
    return () => {
      document.removeEventListener("pointerdown", onOutside, true);
      document.removeEventListener("mousedown", onOutside, true);
      document.removeEventListener("keydown", onEscape, true);
      window.removeEventListener("keydown", onEscape, true);
    };
  }, [open, menuId, items.length, close, focusItem, triggerRef]);

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        onClick={() => (open ? close(true) : openMenu("first"))}
        onKeyDown={(event) => {
          const intent = triggerKeyIntent(event.key);
          if (!intent) return;
          event.preventDefault();
          if (open) focusItem(intent === "last" ? Math.max(items.length - 1, 0) : 0);
          else openMenu(intent);
        }}
        className="rounded p-0.5 text-dim opacity-0 transition-opacity hover:text-strong focus-visible:opacity-100 disabled:opacity-30 group-hover/card:opacity-100 aria-expanded:opacity-100"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>

      {open ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-labelledby={triggerId}
          tabIndex={-1}
          onKeyDown={(event) => {
            const intent = menuKeyIntent(event.key);
            if (intent === null) return;
            if (intent === "close") {
              // Escape is swallowed; Tab is not, so focus walks on from the
              // trigger we just returned it to.
              if (event.key === "Escape") event.preventDefault();
              close(true);
              return;
            }
            event.preventDefault();
            focusItem(rovingIndex(activeIndex.current, items.length, intent));
          }}
          className="absolute right-0 top-full z-20 mt-1 w-48 origin-top-right overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
        >
          {items.map((item, index) => (
            <button
              key={item.key}
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onFocus={() => {
                activeIndex.current = index;
              }}
              onClick={() => {
                close(true);
                item.onSelect();
              }}
              className={`block w-full px-3 py-2 text-left text-xs transition-colors ${
                index > 0 ? "border-t border-line-soft" : ""
              } ${
                item.tone === "danger"
                  ? "text-reject hover:bg-reject/10"
                  : "text-muted hover:bg-surface-2 hover:text-strong"
              }`}
            >
              {item.label}
              {item.hint ? (
                <span className="mt-0.5 block font-mono text-[9px] leading-tight text-dim">
                  {item.hint}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
