/**
 * Candidate 05 — the cursor pane-walk, storyboarded.
 *
 * NOT A RECORDING, and drawn so it cannot be mistaken for one: the four
 * frames below are schematic wireframes — grey blocks, dashed borders, no
 * product pixels. A real take would be a footage run at ~600px: the pointer
 * (real `pointerdown`/`pointermove` events driving the shipped board) opens
 * the interview row, the pane docks, the trail and gate meter scroll past,
 * the pane closes. The cursor in frame would be synthesized AT CAPTURE TIME
 * from the same events that drove the take — `@remotion/mac-cursors`
 * (first published 2026-08-18) draws it.
 *
 * This candidate is blocked on a rule, and honestly so:
 * scripts/footage/README.md says "No fake cursors". Building it means
 * AMENDING that rule, not ignoring it — see the quoted amendment below. If
 * the amendment feels like a loophole, the honest answer is to not build
 * this one; the rule exists because drawing on footage is where marketing
 * pages start lying.
 */

const BEATS = [
  { n: "1", label: "Pointer crosses the resting board" },
  { n: "2", label: "It opens the interview row — the pane docks" },
  { n: "3", label: "The trail scrolls past; the gate meter is visible" },
  { n: "4", label: "The pane closes; the board rests" },
] as const;

/** A deliberately schematic frame: blocks, not product. */
function Wireframe({ beat }: { beat: (typeof BEATS)[number] }) {
  const paneOpen = beat.n === "2" || beat.n === "3";
  return (
    <figure className="min-w-0">
      <div className="relative flex aspect-[4/3] gap-2 rounded-lg border border-dashed border-line-strong bg-surface p-3">
        {/* the board's rows */}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className={`h-6 rounded ${paneOpen && i === 1 ? "bg-viz-rules/25" : "bg-surface-2"}`}
            />
          ))}
        </div>
        {/* the docked pane */}
        {paneOpen && (
          <div className="flex w-2/5 flex-col gap-2 rounded border border-line bg-surface-2/60 p-2">
            <div className="h-3 w-2/3 rounded bg-surface-2" />
            <div className="h-2 rounded bg-surface-2" />
            <div className="h-2 rounded bg-surface-2" />
            {beat.n === "3" && <div className="mt-auto h-2 rounded bg-viz-rules/30" />}
          </div>
        )}
        {/* the cursor — schematic arrow, positioned per beat */}
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className={`absolute h-4 w-4 fill-strong ${
            beat.n === "1"
              ? "left-[30%] top-[55%]"
              : beat.n === "2"
                ? "left-[38%] top-[32%]"
                : beat.n === "3"
                  ? "left-[72%] top-[60%]"
                  : "left-[85%] top-[15%]"
          }`}
        >
          <path d="M5 3l14 9-6 1.5L15 20l-3 1-2-6.5L5 18V3z" />
        </svg>
        <span className="label-caps absolute bottom-2 right-2 text-review">storyboard</span>
      </div>
      <figcaption className="mt-2 text-xs leading-relaxed text-dim">
        <span className="font-mono text-viz-rules">{beat.n}</span> · {beat.label}
      </figcaption>
    </figure>
  );
}

export function CursorStoryboard() {
  return (
    <div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {BEATS.map((beat) => (
          <Wireframe key={beat.n} beat={beat} />
        ))}
      </div>
      <div className="mt-6 max-w-2xl rounded-lg border border-line-soft bg-surface p-4 text-sm leading-relaxed">
        <p className="label-caps mb-2">The rule this needs amended</p>
        <p className="text-dim">
          scripts/footage/README.md currently reads{" "}
          <span className="text-muted">&ldquo;No fake cursors, no invented UI, no motion graphics laid
          over the footage.&rdquo;</span>{" "}
          Proposed amendment: a cursor may appear only when it is synthesized at capture time from
          the real pointer events that drove the take, and the README discloses the synthesis. A
          cursor drawn over frames in post stays banned. No disclosure norm exists anywhere in the
          industry for this — Applied would be writing one, which fits a product whose
          differentiator is showing its work.
        </p>
      </div>
    </div>
  );
}
