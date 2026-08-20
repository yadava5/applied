/**
 * 03c — follow one letter: the storyboard. A tracking shot no DOM take can
 * make: several arrivals stream toward the board, the camera locks onto ONE
 * — Kestrel's assessment, never a rejection — and in flight the envelope
 * unfolds into the real mail surface, the reading light sweeps it (02a's
 * grammar), it folds into a board row mid-air, and the camera rides it down
 * into its stage group.
 *
 * This is the lab's one recording: continuous 3D-feeling travel with a
 * mid-flight transformation needs composited footage, which is exactly what
 * the Remotion pipeline exists for. Until that take is rendered the plate
 * stays STAMPED — no motion is faked here — and commissioning it includes
 * amending the footage README's cursor covenant in the recorded-events
 * terms the old plate 05 set out: anything synthesized must be synthesized
 * at capture time from the real events that drove the take, and disclosed.
 */

const SHOTS = [
  {
    n: 1,
    name: "The stream",
    what: "Wide on the board's top edge; three envelopes drift down toward it, spaced like real mail — no rush, no swarm.",
  },
  {
    n: 2,
    name: "The lock",
    what: "The camera picks one envelope — Kestrel's — and tracks it; the others soften and fall away behind the focal plane.",
  },
  {
    n: 3,
    name: "The unfold",
    what: "In flight, the envelope unfolds into the real mail surface at full legibility; the reading light sweeps it once (02a's highlight grammar, same recorded offsets).",
  },
  {
    n: 4,
    name: "The fold",
    what: "The mail folds into a real board row — company, role, stage chip — still travelling; nothing about the row is drawn for the shot.",
  },
  {
    n: 5,
    name: "The seat",
    what: "The camera rides the row down into the assessment group and settles as the board absorbs it; the group heading's count ticks up by one.",
  },
] as const;

export function FollowOneLetter() {
  return (
    <div>
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {SHOTS.map((shot) => (
          <li
            key={shot.n}
            className="flex flex-col rounded-xl border border-dashed border-review/40 bg-surface p-4"
          >
            <p className="label-caps text-review">shot {shot.n}</p>
            <p className="mt-1.5 text-sm font-medium text-strong">{shot.name}</p>
            <p className="mt-2 text-xs leading-relaxed text-dim">{shot.what}</p>
          </li>
        ))}
      </ol>
      <p className="mt-4 max-w-2xl text-xs leading-relaxed text-dim">
        Two lies this take must not tell, written into the brief for the render: the in-flight
        reading must not imply the sync frame classified anything live (the caption stays scoped
        to the pass, as in 03a/03b), and the tracked letter is never a rejection — no rejection
        has ever arrived by sync; they enter through the review gate.
      </p>
    </div>
  );
}
