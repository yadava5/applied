"use client";

import Link from "next/link";
import { useLinkStatus } from "next/link";
import type { ReactNode } from "react";

import { useDemoMode } from "./demo-mode";
import { demoHrefFor } from "./nav";

/**
 * The rail's destination link: a `<Link>` that answers the press before the
 * payload arrives. Shared by the desktop `Sidebar` and the mobile menu in
 * `TopBar` so the two cannot drift, exactly as `nav.ts` shares their targets.
 *
 * WHY: every in-app navigation pays the whole origin cost, cold, and the rail
 * had nothing to say while it happened. Measured on production (2026-08-14,
 * signed-in, `getapplied.vercel.app`), click → settled:
 *
 *   · /dashboard  986 ms of RSC round-trip, 1032 ms to the last mutation
 *   · /inbox      876 ms, then five more proxy reads landing at 907–1187 ms
 *   · /settings   653 ms
 *   · /import     473 ms
 *
 * with first paint (the route's own `loading.tsx`) landing 61–403 ms in. That
 * leading gap is what "the tab takes a second and nothing happens" is.
 *
 * PREFETCH IS NOT THE FIX HERE, AND THAT WAS MEASURED — do not re-derive it.
 * Every `(app)` route is `ƒ Dynamic`. Next 16.3 issues NO prefetch for them at
 * any setting: a fresh production load fired zero prefetch requests, a real
 * 1.5 s pointer hover fired zero, and a build with `prefetch={true}` hard-coded
 * on all four rail links — four anchors visible in the viewport, 4 s of settle,
 * network capture proven live by the 16 other requests it recorded — fired zero
 * `_rsc` requests. The positive control in the same session: the /login page
 * DID prefetch `/`, `/signup` and `/forgot-password`, which are `○ Static`. So
 * the mechanism works and simply declines dynamic routes without PPR.
 * `unstable_dynamicOnHover` rides the same path and changes nothing; it is also
 * absent from the `next/link` public prop types. Making prefetch work here means
 * enabling PPR / cache components, which is a different and much larger change.
 *
 * So the wait is real and the honest thing is to answer it. `useLinkStatus`'s
 * `pending` flips synchronously on click, so the item takes the accent bar the
 * ACTIVE item wears, immediately: the rail says where you are going at 0 ms
 * instead of sitting inert until the route's skeleton arrives. It is the same
 * bar, in the same place, at the same size — the destination's own treatment
 * arriving early, not a second vocabulary invented for waiting.
 */

/**
 * The pending accent. Absolutely positioned, so it can never move the item it
 * is drawn on — the active bar it stands in for is positioned identically, and
 * an item that grew or shifted on press would be a CLS defect on the control
 * you just pressed.
 *
 * Must be a CHILD of `<Link>`: `useLinkStatus` reads a context that `Link`
 * itself provides, so it is unreadable from the element carrying the className.
 * That is why the pending state is painted rather than composed into the
 * anchor's own classes.
 */
function PendingAccent() {
  const { pending } = useLinkStatus();
  if (!pending) return null;
  return (
    <>
      <span
        aria-hidden="true"
        className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-viz-rules motion-safe:animate-pulse"
      />
      {/* Said once, plainly, for a reader who cannot see the bar. `aria-live` is
          deliberately absent: the route's own heading announces the arrival, and
          two announcements for one navigation is noise. */}
      <span className="sr-only">Loading</span>
    </>
  );
}

export function NavLink({
  href,
  active,
  className,
  onClick,
  children,
}: {
  href: string;
  /** Whether this item is the current route; the caller owns the styling. */
  active: boolean;
  className: string;
  onClick?: () => void;
  children: ReactNode;
}) {
  // In fixture mode every signed-in destination is an auth bounce, so the item
  // resolves to its public twin (`demoNavHrefs`). Rewritten HERE, at the one
  // anchor both the desktop rail and the mobile menu render, so the two can no
  // more disagree about where a demo item goes than about what it is called.
  // `active` still keys off the canonical href — the caller's `isNavItemActive`
  // already treats the twins as their originals.
  const demo = useDemoMode();
  return (
    <Link
      href={demo ? demoHrefFor(href) : href}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={className}
    >
      {/* The active bar wins when both could show — arriving where you already
          are should not repaint the bar you are looking at. */}
      {active ? null : <PendingAccent />}
      {children}
    </Link>
  );
}
