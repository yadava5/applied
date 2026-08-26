/**
 * The shell's ambient channel — two one-way signals for the rail's ambient
 * mail field (`components/shell/AmbientRail`).
 *
 * PULSES: "something real just landed". Published only by surfaces that
 * actually changed the board — `SyncBar` when a run filed, updated or removed
 * rows (live and simulated alike, including the staleness auto-sync, which
 * funnels through the same `runSync`), and each board transport's
 * `changeStatus` funnel when a stage write succeeded. The mounted field
 * answers with a flurry of resolves sized to the count. A publish with no
 * listener is a no-op by design: below `md` the rail does not exist, and an
 * event with no audience costs nothing. What is deliberately NOT published:
 * navigations, renders, failed writes — a field that stirred for nothing
 * would train the eye to ignore it, and its whole value is meaning motion.
 *
 * OVERRIDE: the Settings toggle's immediate half. The saved preference
 * travels server-side (user metadata → the `(app)` layout → `Sidebar`), which
 * is the durable truth but only lands with `router.refresh()`; the override
 * makes the click take effect the moment the save succeeds, and the refreshed
 * server prop then agrees with it. `null` = no override this session. Shaped
 * for `useSyncExternalStore` (stable snapshot, `null` server snapshot).
 *
 * Module-level state is safe here for the same reason as `scan-bus`: only
 * client components touch it, from effects and event handlers, never during a
 * server render. Dependency-free so `node --test` can load it.
 */

type PulseListener = (count: number) => void;

const pulseListeners = new Set<PulseListener>();

/** The mounted field subscribes on mount; returns the unsubscribe. */
export function onAmbientPulse(fn: PulseListener): () => void {
  pulseListeners.add(fn);
  return () => {
    pulseListeners.delete(fn);
  };
}

/** Announce that `count` real things just changed on the board (≥1). */
export function publishAmbientPulse(count = 1): void {
  const n = Math.max(1, Math.floor(count));
  for (const fn of pulseListeners) fn(n);
}

// --- The toggle's session override -------------------------------------------

let override: boolean | null = null;
const overrideListeners = new Set<() => void>();

export function onAmbientOverride(fn: () => void): () => void {
  overrideListeners.add(fn);
  return () => {
    overrideListeners.delete(fn);
  };
}

/** `getSnapshot`: the session's override, or `null` for "server prop wins". */
export function readAmbientOverride(): boolean | null {
  return override;
}

/** `getServerSnapshot`: no click has happened on the server, ever. */
export function serverAmbientOverride(): null {
  return null;
}

export function setAmbientOverride(on: boolean): void {
  override = on;
  for (const fn of overrideListeners) fn();
}
