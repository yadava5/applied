/**
 * One-slot signal for "open the Removed rows panel".
 *
 * The panel lives inside `PipelineBoard` (the one client component that holds
 * the transport AND outlives every row, so a restore can put a row back into
 * the list the reader is looking at), but its three doors are in three
 * different subtrees: the command row's `⋯` menu is `SyncBar`, the
 * nothing-matched line is the board's own worklist, and the tombstone is an
 * `ApplicationRow` that is about to unmount. Threading a callback through the
 * server page reaches none of them.
 *
 * Same shape and the same reasoning as `scan-bus.ts`, down to the boolean
 * return: a door that raises this signal with nothing mounted must be able to
 * say so rather than silently doing nothing — the inert board on the landing
 * page mounts no panel at all.
 *
 * Module-level state is safe here for the same reason as `rowMenuRegistry`:
 * only client components touch it, and only from effects and event handlers —
 * never during a server render. Dependency-free so `node --test` can load it.
 */

type Listener = () => void;

let listener: Listener | null = null;

/** The mounted panel subscribes on mount; returns the unsubscribe. */
export function onRemovedRequest(fn: Listener): () => void {
  listener = fn;
  return () => {
    if (listener === fn) listener = null;
  };
}

/**
 * Ask the mounted panel to open. Returns whether anything was listening, so a
 * door can render itself honestly instead of offering a route to nowhere.
 */
export function requestRemoved(): boolean {
  if (listener === null) return false;
  listener();
  return true;
}
