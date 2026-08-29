import type { CandidateApplication, ReviewAssignment } from "@/lib/dashboard/review";
import { cn } from "@/lib/utils";

/**
 * "Which application is this about?" — asked in ONE voice, everywhere it is
 * asked.
 *
 * One employer can hold several applications (four Amazon roles in one evening
 * is the proven case), so a rejection from that employer is ambiguous until the
 * user says which row it answers. Two surfaces have to put that question: the
 * needs-review queue (`ReviewQueue`, #554) and the correction control on stored
 * mail (`ReclassifyControl`, #560). This is the one renderer of it.
 *
 * IT IS ONE COMPONENT ON PURPOSE. A second, differently-worded way of asking
 * the same thing is worse than not asking twice: the two wordings drift, the
 * user learns one of them, and — the concrete cost here — the e2e that gates
 * the queue's copy says nothing about the ledger's. This estate has paid for
 * "two renderers, one number" before. `asksWhichApplication` is the matching
 * half: one predicate decides WHEN the question is put, this decides how it
 * reads.
 *
 * NOTHING IS PRE-SELECTED. `assignment === null` is "unanswered", and every
 * radio is then unchecked. The option that DISCARDS the question used to be the
 * default (`checked={assignment === null}` on "not one of these"), so a user
 * who read the subject, chose a stage and clicked classify had answered "none
 * of my applications at this employer" without ever choosing it — 19 destroyed
 * and 58 scattered applications over 2,701 replayed answers (#554). The caller
 * gates its own submit on `canSubmitReview`, which is what makes "unanswered"
 * unsendable rather than merely unchecked.
 *
 * The question and its options are PROSE and are set in the text face. Only the
 * board's machine values elsewhere on these rows (confidence, dates) are mono.
 */
export function ApplicationPicker({
  name,
  candidates,
  assignment,
  onChange,
  disabled,
  className,
}: {
  /**
   * The radio group's name — unique per message. Several of these render in one
   * list, and a shared name would make one pick clear another row's.
   */
  name: string;
  candidates: readonly CandidateApplication[];
  assignment: ReviewAssignment;
  onChange: (assignment: ReviewAssignment) => void;
  disabled?: boolean;
  /** The caller's own layout (`mt-2` in a list row, `basis-full` in a flex row). */
  className?: string;
}) {
  return (
    <fieldset className={cn("rounded border border-line px-2.5 py-2", className)}>
      <legend className="px-1 text-[11px] text-muted">
        which application is this about?
      </legend>
      <div className="space-y-1">
        {candidates.map((candidate) => (
          <label
            key={candidate.id}
            className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-muted hover:text-strong"
          >
            <input
              type="radio"
              name={name}
              // The answer is readable from the DOM, which is what lets a
              // browser test assert that the id the user picked is the id the
              // request carried. Without it the radio's identity lives only in
              // a closure and the wire between the two is untestable — the gap
              // this control shipped through.
              value={candidate.id}
              checked={assignment === candidate.id}
              onChange={() => onChange(candidate.id)}
              disabled={disabled}
              className="h-3 w-3 accent-[var(--text-strong)]"
            />
            <span className="min-w-0 truncate">
              {candidate.position.trim() || "role not captured"}
              <span className="text-dim"> · {candidate.status}</span>
            </span>
          </label>
        ))}
        <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-muted hover:text-strong">
          <input
            type="radio"
            name={name}
            value="none"
            checked={assignment === "none"}
            onChange={() => onChange("none")}
            disabled={disabled}
            className="h-3 w-3 accent-[var(--text-strong)]"
          />
          {/* The label says what the product will DO, because what it used to
              do was file against the oldest row at this employer — the opposite
              of what "not one of these" promises. Choosing it opens a row,
              which is what a lifecycle message about an application the board
              does not hold actually means. */}
          <span>none of these — track it as a new application</span>
        </label>
      </div>
    </fieldset>
  );
}
