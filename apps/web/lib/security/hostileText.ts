/**
 * Neutralise the Unicode code points that let a stranger's mail headers lie
 * about what is on the screen — and report that they were there.
 *
 * WHY THIS EXISTS (#424). Every subject and sender this product draws came
 * from someone else's outbox. `/import` is public and unauthenticated, so the
 * whole path is attacker-influenced by construction: a stranger sends mail
 * whose headers are chosen to mislead and the victim exports and imports it.
 * React escapes MARKUP, not text direction and not invisible characters, so
 * both of the following rendered faithfully and neither was detectable by
 * reading the source:
 *
 *   1. A subject of `Payroll ` + U+202E + `gpj.exe` + U+202C renders on screen
 *      as `Payroll exe.jpg`. The bytes say `.exe`. The screen says `.jpg`.
 *   2. `no-reply` + U+200B + `@greenhouse.io` renders, at 3x device pixel
 *      ratio, to a BYTE-IDENTICAL image to the genuine address — same SHA-256,
 *      both 8,522 bytes. Not "hard to tell apart": identical. Neither a reader
 *      nor a screenshot diff can separate them.
 *
 * NOTE THAT NEITHER EXAMPLE IS WRITTEN OUT LITERALLY ABOVE, and no literal
 * member of the set appears anywhere in this file. Every one is spelled with a
 * `\u` escape. A source file that contains a raw U+202E reverses its own text
 * in every editor and diff that renders it, which is the same defect this
 * module exists to fix, wearing a reviewer's hat instead of a user's. The
 * suite asserts this file stays clean.
 *
 * WHY A SENTINEL AND NOT A STRIP — THIS IS THE LOAD-BEARING DECISION.
 * The obvious fix is to delete these code points. For a SENDER that is worse
 * than doing nothing. Strip the zero-width space out of the forged
 * `no-reply` + U+200B + `@greenhouse.io` and what is left is exactly
 * `no-reply@greenhouse.io` — the genuine address, character for character. The
 * row would then render, in clean unambiguous text, a claim that is FALSE, and
 * it would render it beside a confidence chip that lends it an air of having
 * been checked. Stripping converts a forgery into a perfect impersonation.
 * That is why the sentinel is forced here rather than merely preferred, and it
 * is a stronger reason than the one #424 gives (which is about lost signal).
 *
 * So every neutralised code point is REPLACED, one for one, with U+FFFD
 * REPLACEMENT CHARACTER. Three reasons for that character specifically:
 *
 *   - It is Unicode's own answer to "a character was here that this text
 *     cannot faithfully carry", which is precisely the statement being made.
 *   - It is exactly one code point, so the substitution is LENGTH-PRESERVING.
 *     Every row that draws a subject is `truncate`d; an expansion form such as
 *     GitHub's inline `<U+202E>` badge costs 8 characters per occurrence, so
 *     200 injected zero-widths would become 1,600 characters and evict the real
 *     subject from the line. That turns a legibility defect into a legibility
 *     denial, which is a worse bug than the one being fixed.
 *   - Every font in the stack has it, and it is conspicuous at 11px.
 *
 * What the sentinel costs, said plainly: the string on screen is no longer the
 * string in the message, and a subject that genuinely contains U+FFFD (real
 * mojibake from a decoding failure upstream) is indistinguishable from our
 * mark. `found` is what settles that — it is non-empty only when WE replaced
 * something, and it is what the row's flag is drawn from.
 *
 * AND THE FLAG IS NOT OPTIONAL, which is the half of #424 that is usually
 * skipped. A message that contained a direction override is a message worth
 * flagging, because the sender chose to put it there. Cleaning it quietly
 * makes the row honest and the mail look ordinary, and that is a real loss of
 * signal rather than a cosmetic one. `inspectHostileText` therefore returns
 * evidence, not just text, and `components/mail/MailText.tsx` draws it.
 *
 * SCOPE, AND THE TWO THINGS DELIBERATELY OUTSIDE IT.
 *   - HOMOGLYPHS are not handled. A Cyrillic `greenhouse.io` is visually
 *     indistinguishable but NOT byte-identical, so unlike the zero-width case
 *     it is detectable by comparison. It is a different and much harder
 *     problem and #424 separates the two on purpose.
 *   - U+200E LEFT-TO-RIGHT MARK and U+200F RIGHT-TO-LEFT MARK sit immediately
 *     above U+200D and they DO affect direction, but they are implicit marks
 *     rather than overrides: they cannot reverse a run the way U+202E can,
 *     only nudge a neutral character's resolved direction. #424's ranges stop
 *     at U+200D, so they pass through, and a test asserts that they do — an
 *     exclusion nobody wrote down is indistinguishable from an oversight.
 *
 * Deliberately dependency-free (no React, no `@/` alias, no generated schema)
 * so `tests/unit/` can load it directly under Node's type stripping — the same
 * rule as `lib/mail/filed.ts` and `lib/dashboard/review.ts`.
 */

/**
 * The thirteen code points, exactly as #424 names them.
 *
 * U+202A–U+202E  the deprecated bidi embedding/override controls: LRE, RLE,
 *                PDF, LRO, RLO. U+202E RIGHT-TO-LEFT OVERRIDE is the one that
 *                rewrote `gpj.exe` into `exe.jpg`.
 * U+2066–U+2069  the modern bidi isolates: LRI, RLI, FSI, PDI. Same power,
 *                current spelling — a fix that covered only the deprecated
 *                range would be bypassed by using the new one.
 * U+200B–U+200D  ZERO WIDTH SPACE, NON-JOINER, JOINER. Zero advance width.
 * U+FEFF         ZERO WIDTH NO-BREAK SPACE (the BOM, when it is not at the
 *                start of a stream). Zero advance width.
 *
 * Kept as an exported array rather than only as the range literal below so the
 * suite can enumerate it and assert one case per member. A set needs a case
 * per member, and a test that only covers U+202E proves nothing about U+2066.
 */
export const HOSTILE_CODE_POINTS: readonly string[] = [
  "\u202A",
  "\u202B",
  "\u202C",
  "\u202D",
  "\u202E",
  "\u2066",
  "\u2067",
  "\u2068",
  "\u2069",
  "\u200B",
  "\u200C",
  "\u200D",
  "\uFEFF",
];

/**
 * The matcher. Ranges rather than an alternation over the array above so the
 * engine can settle this with a single character-class test, and because
 * ranges are how #424 specifies it. The suite cross-checks the two against
 * each other in both directions, so they cannot drift apart.
 *
 * `g` is safe here because this module only ever hands the regex to
 * `String.prototype.replace`, which resets `lastIndex` on every call. It is
 * never used with `.test()`, which does not, and which is how a module-level
 * global regex becomes an every-other-call bug.
 */
const HOSTILE = /[\u202A-\u202E\u2066-\u2069\u200B-\u200D\uFEFF]/g;

/** What every neutralised code point becomes. See the header for why. */
export const HOSTILE_SENTINEL = "\uFFFD";

/** `"\u202E"` -> `"U+202E"`. The machine value, for the flag's detail line. */
function codePointLabel(character: string): string {
  return `U+${character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`;
}

export interface InspectedText {
  /** Safe to render. Same length as the input, sentinels in place. */
  readonly text: string;
  /**
   * One `U+XXXX` label per OCCURRENCE, in the order they appeared — so
   * `found.length` is a count the flag can state, and duplicates are not
   * collapsed here because "three overrides" and "one override" are different
   * facts about the sender.
   */
  readonly found: readonly string[];
}

/**
 * Neutralise `value` and say what was in it.
 *
 * Null, undefined and non-strings answer with an empty string and no findings
 * rather than throwing: every caller is a render path, and a row that throws
 * on a malformed header takes the whole list down with it.
 */
export function inspectHostileText(value: string | null | undefined): InspectedText {
  if (typeof value !== "string" || value === "") return { text: "", found: [] };
  const found: string[] = [];
  const text = value.replace(HOSTILE, (character) => {
    found.push(codePointLabel(character));
    return HOSTILE_SENTINEL;
  });
  return { text, found };
}

/**
 * The neutralised text alone.
 *
 * This is the form for the places that take a STRING and cannot hold an
 * element: `aria-label`, `title`, and the template literals that build an
 * accessible name. Those matter as much as the visible line, and for a sharper
 * reason — a bidi override is not scoped to the substring it sits in. An
 * UNTERMINATED U+202E inside `` `Open “${subject}” in Gmail` `` reverses
 * everything after it, so a hostile subject rewrites the REST of the control's
 * announced name, not just its own quoted part.
 *
 * These sites get no flag: the row's own subject and sender already carry one,
 * and stuffing a warning into every accessible name would bury the name the
 * label exists to give. That trade is deliberate.
 */
export function safeText(value: string | null | undefined): string {
  return inspectHostileText(value).text;
}

/** Whether this string carries anything we would neutralise. */
export function hasHostileText(value: string | null | undefined): boolean {
  return inspectHostileText(value).found.length > 0;
}

/**
 * The sentence the flag announces to a screen reader and shows on hover.
 *
 * DISTINCT code points are listed, but the COUNT is of occurrences: an
 * attacker can inject five hundred zero-widths, and a title attribute holding
 * five hundred repetitions of `U+200B` is its own small denial of service.
 * There are only thirteen possible labels, so once deduplicated the list is
 * bounded by construction and needs no arbitrary cap.
 */
export function hostileTextNote(found: readonly string[]): string {
  const distinct = [...new Set(found)];
  const plural = found.length === 1 ? "" : "s";
  return (
    `${found.length} hidden character${plural} (${distinct.join(", ")}) — ` +
    `invisible or direction-changing code point${plural} the sender put in this text. ` +
    `Each one is drawn as a marker so it cannot rewrite what you read.`
  );
}
