"use client";

import Link from "next/link";
import { useRef, type ReactNode } from "react";

/**
 * A primary link with a magnetic pull: while the pointer is near, the button
 * eases toward it and its contents drift a touch further for parallax; on leave
 * it springs back to rest. Purely a pointer enhancement layered on top of the
 * caller's className — focus, activation, and client-side navigation are the
 * plain <Link>'s. Under reduced-motion the magnet is never wired up, so it is an
 * ordinary link.
 */
export function MagneticLink({
  href,
  className,
  children,
  strength = 0.4,
  radius = 90,
}: {
  href: string;
  className?: string;
  children: ReactNode;
  strength?: number;
  radius?: number;
}) {
  const ref = useRef<HTMLAnchorElement>(null);
  const inner = useRef<HTMLSpanElement>(null);

  const reduce = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const onMove = (e: React.MouseEvent<HTMLAnchorElement>) => {
    const el = ref.current;
    if (!el || reduce()) return;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const dist = Math.hypot(dx, dy);
    const pull = Math.max(0, 1 - dist / (r.width / 2 + radius));
    el.style.transition = "transform 120ms ease-out";
    el.style.transform = `translate(${dx * strength * pull}px, ${dy * strength * pull}px)`;
    if (inner.current) {
      inner.current.style.transition = "transform 120ms ease-out";
      inner.current.style.transform = `translate(${dx * strength * 0.35 * pull}px, ${dy * strength * 0.35 * pull}px)`;
    }
  };

  const reset = () => {
    const el = ref.current;
    if (!el) return;
    el.style.transition = "transform 450ms cubic-bezier(0.22, 1.3, 0.36, 1)";
    el.style.transform = "translate(0, 0)";
    if (inner.current) {
      inner.current.style.transition = "transform 450ms cubic-bezier(0.22, 1.3, 0.36, 1)";
      inner.current.style.transform = "translate(0, 0)";
    }
  };

  return (
    <Link
      ref={ref}
      href={href}
      className={className}
      onMouseMove={onMove}
      onMouseLeave={reset}
      onBlur={reset}
    >
      <span ref={inner} className="inline-flex items-center gap-1.5">
        {children}
      </span>
    </Link>
  );
}
