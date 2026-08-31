import { TriangleAlert } from "lucide-react";

import { hostileTextNote, inspectHostileText } from "@/lib/security/hostileText";

/**
 * Draw a string that came from a stranger's outbox — a subject, a sender, an
 * employer name, a snippet — so the screen cannot lie about what the bytes
 * say, and say so out loud when it tried to.
 *
 * WHY A COMPONENT AND NOT JUST A CALL TO `safeText` (#424). Neutralising is
 * only half the job. The half that gets skipped is TELLING THE READER: a
 * message that carried a direction override is a message worth flagging,
 * because the sender chose to put it there. Cleaning it quietly leaves the row
 * honest and the mail looking ordinary, which loses the only signal the reader
 * had. Pairing the two here means a render path cannot take the cleaning and
 * silently drop the warning — there is one thing to call, and it does both.
 *
 * `lib/security/hostileText.ts` carries the reasoning for the sentinel and for
 * which thirteen code points are in the set. Read it before changing either.
 *
 * WHERE THE FLAG SITS, AND WHY IT IS FIRST. Every row that draws a subject
 * wraps it in `truncate` (`overflow: hidden; text-overflow: ellipsis`). A
 * warning appended AFTER the text is the first thing a long subject pushes off
 * the end of the line, so an attacker would silence the flag by padding the
 * subject — the fix would defeat itself on exactly the inputs it exists for.
 * Rendered first, it is the last thing an ellipsis can reach. It also reads in
 * the right order: the warning arrives before the text it is about.
 *
 * HOOK-FREE ON PURPOSE. `tests/unit/helpers/renderTsx.mjs` renders a leaf by
 * calling it (`markup(MailSnippet({ snippet }))`), which is the cheapest
 * executable proof available here. A `useState` would end that, and this is
 * the component the whole fix rests on.
 */

/**
 * The warning. Shape AND words, never colour alone: a triangle, the phrase
 * "hidden characters", and an `sr-only` sentence naming the actual code points
 * for a reader who cannot see either.
 *
 * The chip's own text is the accessible signal rather than an `aria-label` — a
 * bare `<span>` has no role, and an `aria-label` on a roleless element is not
 * reliably announced. `title` is the sighted-mouse supplement, not the only
 * channel; the `sr-only` text is what actually carries the detail.
 *
 * `relative` is load-bearing. Tailwind's `sr-only` is `position: absolute`, and
 * an absolutely positioned child with no positioned ancestor resolves against
 * the initial containing block, which has made the WHOLE document scroll here
 * before. The chip is its own containing block so it cannot.
 *
 * NO RESPONSIVE GATING. The rows around this are full of `hidden sm:inline`
 * and `hidden md:inline`, and matching that idiom would hide a security signal
 * at some widths. It draws at every width, including 1024.
 *
 * The phrase is set in the document's text face, not mono. The code points ARE
 * machine values and would earn mono if they were drawn as visible text, but
 * they are not: they live in the `title` and the `sr-only` sentence, where no
 * face applies. If they are ever surfaced on screen, set those in mono and
 * leave this label alone.
 */
function HiddenCharacterFlag({ found }: { found: readonly string[] }) {
  const note = hostileTextNote(found);
  return (
    <span
      data-testid="hidden-character-flag"
      title={note}
      className="relative mr-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-review/40 px-1.5 py-0.5 align-middle text-[10px] font-semibold uppercase tracking-wide text-review"
    >
      <TriangleAlert className="h-2.5 w-2.5" aria-hidden />
      hidden characters
      <span className="sr-only"> — {note}</span>
    </span>
  );
}

/**
 * A mail-supplied string, neutralised, with its flag when it needed one.
 *
 * Returns a fragment rather than an element so it drops straight into the
 * existing line without changing any row's layout: `{item.subject}` becomes
 * `<MailText value={item.subject} />` and nothing else moves.
 *
 * Callers keep their own empty-value wording (`"(no subject)"`,
 * `"unknown sender"`) — this does not invent one, because a row that says
 * "(no subject)" and a row that says nothing are different products' decisions
 * and they already differ per surface.
 *
 * For an `aria-label`, a `title`, or any other slot that takes a STRING and
 * cannot hold an element, use `safeText` from `lib/security/hostileText.ts`.
 */
export function MailText({ value }: { value: string | null | undefined }) {
  const { text, found } = inspectHostileText(value);
  if (found.length === 0) return <>{text}</>;
  return (
    <>
      <HiddenCharacterFlag found={found} />
      {text}
    </>
  );
}
