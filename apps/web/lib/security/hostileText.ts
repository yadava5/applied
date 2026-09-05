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
 *   2. `no-reply` + U+200B + `@harbourgate.test` renders, at 3x device pixel
 *      ratio, to a BYTE-IDENTICAL image to the genuine address — same SHA-256,
 *      both 8,522 bytes. Not "hard to tell apart": identical. Neither a reader
 *      nor a screenshot diff can separate them.
 *
 * THE ADDRESS ABOVE IS INVENTED AND THE MEASUREMENT IS NOT. #424 measured this
 * against a real applicant-tracking system's no-reply address; the shape is
 * that one, the particulars are invented on a domain RFC 2606 reserves, per
 * `docs/TEST_DATA_POLICY.md`. `scripts/check_test_data.py` does not scan
 * `apps/web/lib/`, so nothing forced this — the policy covers a docstring as
 * much as a fixture, and an address a gate cannot see is exactly the one worth
 * getting right by hand.
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
 * `no-reply` + U+200B + `@harbourgate.test` and what is left is exactly
 * `no-reply@harbourgate.test` — the genuine address, character for character. The
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
 *     SAID EXACTLY, because the tag block below is above the BMP: one code
 *     point in, one code point out, so `[...text].length` never moves. In
 *     UTF-16 units a tag character is TWO and U+FFFD is one, so `.length`
 *     drops by one per tag character. The direction is the safe one — this
 *     substitution can only shorten a string, never grow it — so no input can
 *     pad a flag off the end of a line, which is the property that mattered.
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
 * WHAT THE WIDER SET COSTS, AND WHO PAYS IT. Two of the blocks below have a
 * legitimate use, so a subject that carries one honestly will now draw a marker
 * it did not earn. Both are named here rather than discovered later on a row:
 *
 *   - U+00AD SOFT HYPHEN is a hyphenation HINT: invisible until a line breaks
 *     on it, and German and Hungarian senders do use it in a long compound. A
 *     subject that genuinely carries one now shows a marker in its place.
 *   - The tag block is how an emoji TAG SEQUENCE spells a subdivision flag —
 *     the England, Scotland and Wales flags are a black flag followed by five
 *     tag letters and U+E007F CANCEL TAG. A subject carrying one of those
 *     three renders as a black flag and six markers.
 *
 * Nothing else in the set has a use worth defending in a mail header. The
 * invisible LETTERS (U+115F, U+1160, U+3164, U+FFA0) are Unicode's classic
 * spoofers — category Lo, so they are letters as far as every filler and
 * validator is concerned, and blank as far as the reader is concerned — and the
 * reserved default-ignorables are, by definition, not carrying anything.
 *
 * The trade, in both cases: a visible, self-explaining marker on rare
 * legitimate text beats an invisible impersonation on hostile text. The marker
 * announces itself and the row's flag says which code points it stood in for,
 * so a reader who sees one on a German compound can tell what happened; a
 * reader who is shown the wrong sender cannot tell anything at all. And the
 * cost is bounded by how rare these are on the only text this touches, which is
 * a subject line, a sender and a snippet.
 *
 * SCOPE, AND WHAT IS DELIBERATELY OUTSIDE IT.
 *   - HOMOGLYPHS are not handled. A Cyrillic `harbourgate.test` is visually
 *     indistinguishable but NOT byte-identical, so unlike the zero-width case
 *     it is detectable by comparison. It is a different and much harder
 *     problem and #424 separates the two on purpose.
 *   - THE IMPLICIT MARKS PASS THROUGH: U+200E LEFT-TO-RIGHT MARK, U+200F
 *     RIGHT-TO-LEFT MARK and U+061C ARABIC LETTER MARK.
 *
 *     An earlier version of this file justified that by saying #424's ranges
 *     stopped at U+200D. That reason is dead — the set below is no longer
 *     #424's ranges, and #424's own thread names U+061C — so here is the real
 *     one, and it is a TRADE rather than a claim that these are harmless.
 *
 *     Mail clients inject LRM and RLM into legitimate Hebrew and Arabic
 *     subjects as a matter of routine, to stop a Latin word, a number or a
 *     trailing bracket from resolving the wrong way inside an RTL line.
 *     Neutralising the class would drop a U+FFFD into a large share of every
 *     RTL subject this product will ever draw: a permanent defacement of
 *     legitimate mail, paid for entirely by the readers least able to work
 *     around it, in exchange for closing one corner of one attack.
 *
 *     THE RESIDUAL, SAID OUT LOUD RATHER THAN GLOSSED. An implicit mark meets
 *     attack 2 at the top of this file exactly: it is byte-different and
 *     pixel-identical, so a sender CAN pad an address with one and this module
 *     will pass it through. What it cannot do is attack 1 — it resolves a
 *     neutral character's direction and nothing else, so it cannot reverse a
 *     run and cannot turn `gpj.exe` into `exe.jpg`. We accept an impersonation
 *     residual to keep legitimate bidi text readable. That is the trade; it is
 *     not a finding of harmlessness, and if the residual ever matters more than
 *     the defacement, this is the paragraph to change.
 *
 *     U+061C is here for the same reason as the other two, and it is written
 *     down because a REVIEW found it undeclared. That was the whole defect: the
 *     rule already decided it — the Arabic counterpart of a mark this file had
 *     already ruled on — and nobody had said so. An exclusion nobody wrote down
 *     is indistinguishable from an oversight.
 *   - THE VARIATION SELECTORS PASS THROUGH: U+FE00–U+FE0F and
 *     U+E0100–U+E01EF. U+FE0F is what makes an emoji render as an emoji rather
 *     than as monochrome text, so neutralising the block would mark an ordinary
 *     subject line with an emoji in it — common mail, not hostile mail.
 *     THE RESIDUAL: a chain of variation selectors is invisible and can smuggle
 *     arbitrary data through a subject, and this module passes it. That is a
 *     covert channel rather than a lie about what is on the screen, which is a
 *     different problem from the one #424 states.
 *     THE ASYMMETRY IS DELIBERATE, because it reads like an inconsistency: the
 *     MONGOLIAN free variation selectors (U+180B–U+180D, U+180F) ARE
 *     neutralised. They sit on no emoji path and no mail this product has seen
 *     carries one, so the argument that saves U+FE0F does not reach them.
 *
 * Deliberately dependency-free (no React, no `@/` alias, no generated schema)
 * so `tests/unit/` can load it directly under Node's type stripping — the same
 * rule as `lib/mail/filed.ts` and `lib/dashboard/review.ts`.
 */

/**
 * The set, as RANGES, and the rule that decides what is in it.
 *
 * THE RULE, because a hand list is what got bypassed. Every code point the
 * Unicode standard marks `Default_Ignorable_Code_Point` — the property whose
 * whole meaning is "a renderer that does not know this character should draw
 * NOTHING for it" — except the three exclusions the header argues. That is the
 * same statement as "everything invisible", made by the standard rather than by
 * whoever last edited this file, and it is why the list below can be checked
 * against something outside this repo: the suite sweeps the engine's own
 * Unicode tables and fails when one of them has no ruling here.
 *
 * WHY THAT REPLACED THE HAND LIST. #424 named thirteen code points and a blind
 * review walked straight past them with U+2060 WORD JOINER — zero advance
 * width, bidi class BN, interchangeable with the already-covered U+FEFF, and
 * missing for no reason other than that nobody had thought of it. A list
 * assembled by thinking of things fails exactly that way. Sourcing it from a
 * property means the next character nobody thought of is already in.
 *
 * 3,915 code points, 16 ranges, ascending:
 *  [0x00ad, 0x00ad], // SOFT HYPHEN. A hyphenation hint, and the header argues what it costs.
 *  [0x034f, 0x034f], // COMBINING GRAPHEME JOINER. Invisible, and it joins nothing.
 *  [0x115f, 0x1160], // HANGUL CHOSEONG/JUNGSEONG FILLER. Invisible LETTERS: category Lo,
 *  //   so a validator that only rejects format characters lets them past.
 *  [0x17b4, 0x17b5], // KHMER VOWEL INHERENT AQ and AA. Invisible in modern rendering.
 *  [0x180b, 0x180f], // the Mongolian free variation selectors and the vowel separator.
 *  [0x200b, 0x200d], // ZERO WIDTH SPACE, NON-JOINER, JOINER.
 *  [0x202a, 0x202e], // the deprecated bidi embeddings and overrides: LRE, RLE, PDF, LRO,
 *  //   RLO. U+202E rewrote `gpj.exe` into `exe.jpg`.
 *  [0x2060, 0x206f], // WORD JOINER (the bypass), the four invisible mathematical
 *  //   operators, the reserved U+2065, the modern isolates, and the
 *  //   deprecated format controls.
 *  [0x3164, 0x3164], // HANGUL FILLER. The classic invisible-letter spoofer.
 *  [0xfeff, 0xfeff], // ZERO WIDTH NO-BREAK SPACE, the BOM anywhere but a stream's start.
 *  [0xffa0, 0xffa0], // HALFWIDTH HANGUL FILLER. U+3164's other half.
 *  [0xfff0, 0xfff8], // reserved, and default-ignorable by declaration.
 *  [0x1bca0, 0x1bca3], // the Duployan shorthand format controls.
 *  [0x1d173, 0x1d17a], // the musical-notation format controls (beams, slurs, phrases).
 *  [0xe0000, 0xe00ff], // plane 14 below the variation selectors: LANGUAGE TAG, the 96 tag
 *  //   characters emoji flag sequences are built from, and reserved space.
 *  [0xe01f0, 0xe0fff], // plane 14 above them, all of it reserved.
 *
 * The two blocks that cost something legitimate — U+00AD and the tag block —
 * are argued in the header, as are the three exclusions.
 */
export const HOSTILE_RANGES: readonly (readonly [number, number])[] = [
  [0x00ad, 0x00ad], // SOFT HYPHEN. A hyphenation hint, and the header argues what it costs.
  [0x034f, 0x034f], // COMBINING GRAPHEME JOINER. Invisible, and it joins nothing.
  [0x115f, 0x1160], // HANGUL CHOSEONG/JUNGSEONG FILLER. Invisible LETTERS: category Lo,
  //   so a validator that only rejects format characters lets them past.
  [0x17b4, 0x17b5], // KHMER VOWEL INHERENT AQ and AA. Invisible in modern rendering.
  [0x180b, 0x180f], // the Mongolian free variation selectors and the vowel separator.
  [0x200b, 0x200d], // ZERO WIDTH SPACE, NON-JOINER, JOINER.
  [0x202a, 0x202e], // the deprecated bidi embeddings and overrides: LRE, RLE, PDF, LRO,
  //   RLO. U+202E rewrote `gpj.exe` into `exe.jpg`.
  [0x2060, 0x206f], // WORD JOINER (the bypass), the four invisible mathematical
  //   operators, the reserved U+2065, the modern isolates, and the
  //   deprecated format controls.
  [0x3164, 0x3164], // HANGUL FILLER. The classic invisible-letter spoofer.
  [0xfeff, 0xfeff], // ZERO WIDTH NO-BREAK SPACE, the BOM anywhere but a stream's start.
  [0xffa0, 0xffa0], // HALFWIDTH HANGUL FILLER. U+3164's other half.
  [0xfff0, 0xfff8], // reserved, and default-ignorable by declaration.
  [0x1bca0, 0x1bca3], // the Duployan shorthand format controls.
  [0x1d173, 0x1d17a], // the musical-notation format controls (beams, slurs, phrases).
  [0xe0000, 0xe00ff], // plane 14 below the variation selectors: LANGUAGE TAG, the 96 tag
  //   characters emoji flag sequences are built from, and reserved space.
  [0xe01f0, 0xe0fff], // plane 14 above them, all of it reserved.
];

/**
 * The same set, one string per code point, materialised at load.
 *
 * DERIVED, and that word is load-bearing: this is a convenience for the callers
 * and the suite that want to enumerate members, NOT independent evidence about
 * what the module covers. A test that walks this array and finds the regex
 * agrees has compared the ranges to the regex, which is a real check — those
 * two are written by hand and separately — but it has not checked the ranges
 * against anything. The census in `tests/unit/hostile-text.test.mjs` and the
 * `Default_Ignorable_Code_Point` sweep beside it are what do that.
 */
export const HOSTILE_CODE_POINTS: readonly string[] = HOSTILE_RANGES.flatMap(([first, last]) =>
  Array.from({ length: last - first + 1 }, (_, index) => String.fromCodePoint(first + index)),
);

/**
 * The matcher. One character class rather than an alternation, so the engine
 * settles this with a single test per character, and because ranges are how
 * #424 specifies it.
 *
 * WRITTEN OUT BY HAND, DELIBERATELY NOT DERIVED from `HOSTILE_RANGES`. It is
 * the second of the two artifacts, and the suite cross-checks them against each
 * other in both directions over every code point there is. Generating this from
 * the ranges would make that check compare a thing to itself, which is the
 * defect the census next door exists to correct — so the duplication is the
 * point, and the sweep is what keeps it honest.
 *
 * ASCENDING, matching the order of the ranges above, and it is one long line
 * because it is one character class: sixteen ranges across three planes, and
 * breaking it across lines would only make a missing escape harder to see.
 *
 * `u` IS LOAD-BEARING, TWICE. A `\uXXXX` character class cannot express a code
 * point above the BMP at all, so without the flag the tag block would silently
 * not match — the exact shape of the defect this change exists to fix. And with
 * the flag the replace callback receives the WHOLE astral character rather than
 * a lone surrogate, which is what makes `codePointLabel` report `U+E0020`
 * instead of `U+DB40`. The suite asserts that label.
 *
 * `g` is safe here because this module only ever hands the regex to
 * `String.prototype.replace`, which resets `lastIndex` on every call. It is
 * never used with `.test()`, which does not, and which is how a module-level
 * global regex becomes an every-other-call bug.
 */
const HOSTILE = /[\u00AD\u034F\u115F\u1160\u17B4\u17B5\u180B-\u180F\u200B-\u200D\u202A-\u202E\u2060-\u206F\u3164\uFEFF\uFFA0\uFFF0-\uFFF8\u{1BCA0}-\u{1BCA3}\u{1D173}-\u{1D17A}\u{E0000}-\u{E00FF}\u{E01F0}-\u{E0FFF}]/gu;

/** What every neutralised code point becomes. See the header for why. */
export const HOSTILE_SENTINEL = "\uFFFD";

/** `"\u202E"` -> `"U+202E"`. The machine value, for the flag's detail line. */
function codePointLabel(character: string): string {
  return `U+${character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`;
}

export interface InspectedText {
  /**
   * Safe to render. The same code points as the input, one for one, with a
   * sentinel where each neutralised one was. `.length` is unchanged too except
   * for the astral tag block, where it is one UTF-16 unit shorter per tag
   * character — never longer, which is the direction the header argues.
   */
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
 * DEDUPLICATION IS WHAT BOUNDS THIS, and the bound is no longer small. There
 * are 3,915 possible labels, so a subject that managed to carry one of every
 * member would produce roughly 35 KB of list in a `title` and in the `sr-only`
 * sentence beside it. That is stated rather than waved at: the earlier version
 * of this comment said "only thirteen possible labels … needs no arbitrary
 * cap", which was true of thirteen and is not true of this. What it still buys
 * is the property that matters — the list is linear in the SET, not in the
 * INPUT, so five hundred injected zero-widths produce one label and a count of
 * 500 rather than five hundred repetitions. Reaching the worst case needs a
 * subject carrying thousands of DISTINCT invisible code points, which no header
 * this product stores could hold; if that ever stops being true, cap the
 * distinct list here rather than dropping the deduplication.
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
