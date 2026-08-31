/**
 * The bidi / zero-width neutraliser, asserted the only way it can honestly be
 * asserted: by RENDERING the hostile string and reading what comes out (#424).
 *
 * WHY NOT A UNIT TEST OF THE FUNCTION. A test that calls
 * `inspectHostileText("a" + RLO)` and checks the return value proves the
 * function works. It does not prove that anything on screen calls it, and this
 * is precisely the defect class that source inspection cannot see — `{subject}`
 * looks identical whether the string behind it is honest or reversed. So every
 * assertion below goes through `MailText`, the component the rows draw, and
 * reads the rendered markup. `mail-rows-neutralise-hostile-text.test.mjs`
 * carries the same question one level up: does each ROW call `MailText`.
 *
 * WHY THE HOSTILE CHARACTERS ARE BUILT FROM NUMBERS. Not one literal member of
 * the set appears in this file, or in the module it tests. A source file
 * holding a raw U+202E reverses its own text in every editor, diff and review
 * page that renders it — the same defect, aimed at the reviewer instead of the
 * user. `String.fromCodePoint(0x202e)` says the same thing and stays readable.
 * The last test in this file asserts both files stay clean, so the rule is
 * enforced rather than merely observed.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { importTsx, markup } from "./helpers/renderTsx.mjs";

const { MailText } = await importTsx("components/mail/MailText.tsx");
const { HOSTILE_CODE_POINTS, HOSTILE_SENTINEL, hostileTextNote, inspectHostileText, safeText } =
  await import("../../lib/security/hostileText.ts");

const cp = (n) => String.fromCodePoint(n);

/** The two overrides #424 measured, plus the pop that terminates one. */
const RLO = cp(0x202e); // RIGHT-TO-LEFT OVERRIDE
const PDF = cp(0x202c); // POP DIRECTIONAL FORMATTING
const ZWSP = cp(0x200b); // ZERO WIDTH SPACE
const SENTINEL = cp(0xfffd); // REPLACEMENT CHARACTER — what each one becomes

/**
 * THE SET, WRITTEN OUT INDEPENDENTLY OF THE MODULE.
 *
 * Deliberately not derived from `HOSTILE_CODE_POINTS`: a corpus graded by its
 * own author proves nothing, and an expectation imported from the code under
 * test agrees with it by construction. These thirteen numbers are transcribed
 * from #424's own ranges, so the two lists CAN disagree, and a test below
 * exists solely to notice if they ever do.
 */
const EXPECTED_SET = [
  0x202a, 0x202b, 0x202c, 0x202d, 0x202e, // deprecated embeddings + overrides
  0x2066, 0x2067, 0x2068, 0x2069, // modern isolates
  0x200b, 0x200c, 0x200d, // zero-width space / non-joiner / joiner
  0xfeff, // zero-width no-break space (BOM)
];

/**
 * What a person actually reads: markup with the tags taken out.
 *
 * The point of every assertion here is the RENDERED text, not the source that
 * produced it, so tags go and their attributes go with them — a code point
 * hiding in a `title` is not something a reader sees on the line.
 */
function visibleText(html) {
  return html
    .replace(/<[^>]*>/g, "")
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'");
}

const render = (value) => markup(MailText({ value }));

// ---------------------------------------------------------------------------
// 1. The two attacks #424 measured, rendered.
// ---------------------------------------------------------------------------

test("the RTL-override subject no longer renders a direction it does not have", () => {
  // `Payroll <RLO>gpj.exe<PDF>` renders on screen as `Payroll exe.jpg`.
  const html = render(`Payroll ${RLO}gpj.exe${PDF}`);
  const text = visibleText(html);

  // The override is gone from what is drawn — this is the whole defect.
  assert.equal(text.includes(RLO), false, "U+202E reached the rendered text");
  assert.equal(text.includes(PDF), false, "U+202C reached the rendered text");

  // And the extension the BYTES carry is what is left standing, in order.
  assert.match(text, /gpj\.exe/);
  assert.equal(text.includes("exe.jpg"), false);
});

test("the zero-width forgery does NOT render as the genuine address", () => {
  // This is the assertion that forces a sentinel rather than a strip. #424
  // measured `no-reply<ZWSP>@greenhouse.io` rendering to a BYTE-IDENTICAL
  // image to the real address. Deleting the ZWSP would leave exactly
  // `no-reply@greenhouse.io` — so a "fix" that strips turns a forgery into a
  // perfect impersonation and the row states a falsehood in clean text.
  const text = visibleText(render(`no-reply${ZWSP}@greenhouse.io`));

  assert.equal(text.includes(ZWSP), false, "U+200B reached the rendered text");
  assert.equal(
    text.includes("no-reply@greenhouse.io"),
    false,
    "the forged sender rendered as the genuine address — the sentinel was stripped, not substituted",
  );
  assert.match(text, /no-reply.@greenhouse\.io/);
});

// ---------------------------------------------------------------------------
// 2. A directional control per member of the set. Thirteen code points, two
//    ranges and four singletons: a case that only covers U+202E proves
//    nothing whatever about U+2066.
// ---------------------------------------------------------------------------

test("the module's set is the set #424 names — thirteen code points, no more", () => {
  assert.deepEqual(
    HOSTILE_CODE_POINTS.map((c) => c.codePointAt(0)),
    EXPECTED_SET,
  );
  assert.equal(HOSTILE_CODE_POINTS.length, 13);
});

for (const code of EXPECTED_SET) {
  const label = `U+${code.toString(16).toUpperCase().padStart(4, "0")}`;

  test(`${label} is neutralised in a rendered subject`, () => {
    const html = render(`Offer${cp(code)} from Acme`);
    const text = visibleText(html);

    assert.equal(text.includes(cp(code)), false, `${label} reached the rendered text`);
    assert.equal(text.includes(SENTINEL), true, `${label} left no sentinel behind`);
    // The honest text either side of it survives untouched, in order. The
    // flag renders first, so this is what the LINE ends with.
    assert.ok(
      text.endsWith(`Offer${SENTINEL} from Acme`),
      `${label}: the honest text around it did not survive: ${JSON.stringify(text)}`,
    );
    // And the row says so — neutralising in silence is the half that gets skipped.
    assert.match(html, /data-testid="hidden-character-flag"/, `${label} was cleaned without a flag`);
    assert.ok(html.includes(label), `the flag did not name ${label}`);
  });
}

test("the range literal and the exported array cannot drift apart", () => {
  // Both directions. Every member of the array must match the regex the module
  // actually runs, AND the regex must match nothing the array does not name.
  for (const character of HOSTILE_CODE_POINTS) {
    assert.equal(
      inspectHostileText(character).found.length,
      1,
      `the regex missed ${character.codePointAt(0).toString(16)}, which the array claims`,
    );
  }
  // Sweep the whole neighbourhood the two ranges live in.
  const named = new Set(EXPECTED_SET);
  for (let code = 0x2000; code <= 0x2100; code++) {
    if (named.has(code)) continue;
    assert.equal(
      inspectHostileText(cp(code)).found.length,
      0,
      `the regex caught U+${code.toString(16).toUpperCase()}, which the array does not name`,
    );
  }
});

// ---------------------------------------------------------------------------
// 3. The boundaries. A range needs a case sitting ON each edge and one just
//    outside it, or "202A-202E" and "2029-202F" are the same test.
// ---------------------------------------------------------------------------

const NEIGHBOURS = [
  [0x2029, "PARAGRAPH SEPARATOR, one below the first bidi range"],
  [0x202f, "NARROW NO-BREAK SPACE, one above it — a real character in French typography"],
  [0x2065, "unassigned, one below the isolates"],
  [0x206a, "INHIBIT SYMMETRIC SWAPPING, one above them"],
  [0x200a, "HAIR SPACE, one below the zero-width run"],
  // The interesting exclusion, and it is deliberate. LRM/RLM sit immediately
  // above U+200D and they DO affect direction — but as implicit marks, not
  // overrides: they nudge a neutral character's resolved direction and cannot
  // reverse a run the way U+202E can. #424's ranges stop at U+200D. Asserting
  // the exclusion is what makes it a decision rather than an oversight; if it
  // is ever revisited, this is the test that will say so out loud.
  [0x200e, "LEFT-TO-RIGHT MARK — outside #424's ranges, on purpose"],
  [0x200f, "RIGHT-TO-LEFT MARK — outside #424's ranges, on purpose"],
];

for (const [code, why] of NEIGHBOURS) {
  test(`U+${code.toString(16).toUpperCase()} passes through untouched (${why})`, () => {
    const value = `Offer${cp(code)}letter`;
    const html = render(value);
    assert.equal(visibleText(html), value);
    assert.equal(inspectHostileText(value).found.length, 0);
    assert.doesNotMatch(html, /hidden-character-flag/);
  });
}

// ---------------------------------------------------------------------------
// 4. The negative case. Sanitising a French name would be a regression, and
//    "the text came through" alone would still pass if the flag fired anyway.
// ---------------------------------------------------------------------------

const LEGITIMATE = [
  ["Zoë Lefèvre — Ingénieure, Société Générale", "accented Latin, an em dash"],
  ["株式会社リクルート の応募について", "CJK with kana"],
  ["Влад Петров, Яндекс", "Cyrillic — a homoglyph risk, and NOT this fix's job"],
  ["مرحبا بكم في شركتنا", "Arabic — strongly RTL, and legitimately so"],
  ["Offer! 🎉 congrats", "an emoji, which is astral and must not be split"],
  ["price: 100% — a nbsp and a\ttab", "punctuation that looks exotic but is not"],
];

for (const [value, why] of LEGITIMATE) {
  test(`ordinary non-ASCII is left alone: ${why}`, () => {
    const html = render(value);
    // (a) every character survives, in order;
    assert.equal(visibleText(html), value);
    // (b) the module reports nothing found;
    assert.deepEqual(inspectHostileText(value).found, []);
    // (c) and NO flag is drawn. Without (c) this passes even when the warning
    //     fires on every ordinary name in the list, which would be its own bug.
    assert.doesNotMatch(html, /hidden-character-flag/);
    assert.equal(html.includes(SENTINEL), false);
  });
}

test("a subject that genuinely contains U+FFFD is not mistaken for our mark", () => {
  // Real mojibake from a decoding failure upstream. It renders, and it draws
  // no flag: `found` is what separates our sentinel from a real one, which is
  // the cost of choosing U+FFFD and is stated in the module's header.
  const html = render(`Caf${SENTINEL} interview`);
  assert.equal(visibleText(html), `Caf${SENTINEL} interview`);
  assert.doesNotMatch(html, /hidden-character-flag/);
});

// ---------------------------------------------------------------------------
// 5. The substitution's own properties.
// ---------------------------------------------------------------------------

test("the substitution is length-preserving, so a flag cannot be padded off the line", () => {
  // An expansion form (`<U+200B>`, 8 characters) would let 200 injected
  // zero-widths grow to 1,600 characters and push the real subject out of a
  // `truncate`d row. One code point in, one code point out.
  const value = `a${ZWSP.repeat(200)}b`;
  const { text, found } = inspectHostileText(value);
  assert.equal(text.length, value.length);
  assert.equal(found.length, 200);
});

test("the sentinel reaches the markup as a character, not an entity", () => {
  // A test matching /&#65533;/ would pass against markup no browser shows as a
  // mark, so pin the raw code point.
  const html = render(`x${RLO}y`);
  assert.equal(html.includes(SENTINEL), true);
  assert.equal(html.includes("&#65533;"), false);
  assert.equal(HOSTILE_SENTINEL, SENTINEL);
});

test("null, undefined and the empty string render nothing and never throw", () => {
  for (const empty of [null, undefined, ""]) {
    assert.equal(render(empty), "");
    assert.equal(safeText(empty), "");
  }
});

// ---------------------------------------------------------------------------
// 6. The flag. Its own behaviour, and its own reasons to exist.
// ---------------------------------------------------------------------------

test("the flag names every distinct code point and counts every occurrence", () => {
  const html = render(`${RLO}a${ZWSP}b${ZWSP}c`);
  const note = hostileTextNote(inspectHostileText(`${RLO}a${ZWSP}b${ZWSP}c`).found);

  assert.match(note, /^3 hidden characters \(U\+202E, U\+200B\)/);
  assert.equal(note.includes("U+200B, U+200B"), false, "the note repeated a code point");
  assert.equal(html.includes(note), true, "the note is not on the row");
});

test("the flag says it in words and in shape, never in colour alone", () => {
  const html = render(`x${RLO}y`);
  // The words a sighted reader sees…
  assert.match(html, /hidden characters/);
  // …a shape beside them, hidden from the accessibility tree since the words
  // already carry it…
  assert.match(html, /<svg[^>]*aria-hidden/);
  // …and the detail spelled out for a reader who sees neither.
  assert.match(html, /class="sr-only"/);
  assert.match(html, /U\+202E/);
});

test("the flag is drawn at every width — a security signal is never responsive", () => {
  // These rows are full of `hidden sm:inline` and `hidden md:inline`. Matching
  // that idiom here would hide the warning at some widths, and 1024 is the
  // width this product is actually read at.
  const html = render(`x${RLO}y`);
  // The CLASS attribute alone: the `title` legitimately contains the word
  // "hidden", and matching the whole tag would read that as a Tailwind utility.
  const cls = /data-testid="hidden-character-flag"[^>]*class="([^"]*)"/.exec(html);
  assert.notEqual(cls, null, "the flag has no class attribute to check");
  assert.doesNotMatch(cls[1], /\bhidden\b/);
  assert.doesNotMatch(cls[1], /\b(sm|md|lg|xl):/);
});

test("the flag comes BEFORE the text, so a long subject cannot truncate it away", () => {
  // Every row wraps its subject in `truncate`. A warning appended after the
  // text is the first thing an ellipsis eats, so padding the subject would
  // silence the flag on exactly the inputs it exists for.
  const html = render(`${RLO}${"very long subject ".repeat(40)}`);
  assert.ok(
    html.indexOf("hidden-character-flag") < html.indexOf("very long subject"),
    "the flag is rendered after the text it warns about",
  );
});

test("the flag's sr-only text has a positioned ancestor", () => {
  // Tailwind's `.sr-only` is `position: absolute`. With no positioned ancestor
  // it resolves against the initial containing block and escapes every
  // `overflow` above it, which is how this repo made a whole shell scroll
  // (#149). The chip is its own containing block.
  const html = render(`x${RLO}y`);
  const flag = /<span[^>]*data-testid="hidden-character-flag"[^>]*>/.exec(html)[0];
  assert.match(flag, /\brelative\b/);
});

test("the flag's label is not set in mono — mono means machine value", () => {
  const html = render(`x${RLO}y`);
  const flag = /<span[^>]*data-testid="hidden-character-flag"[^>]*>/.exec(html)[0];
  assert.doesNotMatch(flag, /font-mono/);
});

test("one occurrence reads as one, not as 1 characters", () => {
  assert.match(hostileTextNote(["U+202E"]), /^1 hidden character \(U\+202E\) — invisible or dir/);
  assert.match(hostileTextNote(["U+202E", "U+2066"]), /^2 hidden characters \(U\+202E, U\+2066\)/);
});

// ---------------------------------------------------------------------------
// 7. Our own source must not carry the bytes it defends against.
// ---------------------------------------------------------------------------

test("no file in this fix contains a literal member of the set", () => {
  const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
  // Built from numbers for the same reason everything else here is.
  const hostile = new RegExp(`[${EXPECTED_SET.map((c) => `\\u{${c.toString(16)}}`).join("")}]`, "gu");

  // POSITIVE CONTROL. A scan that silently matches nothing reports "clean" and
  // "never ran" with the same output, so prove the scanner sees one first.
  assert.equal(`ok${RLO}`.match(hostile).length, 1, "the scanner matches nothing at all");

  for (const rel of [
    "lib/security/hostileText.ts",
    "components/mail/MailText.tsx",
    "tests/unit/hostile-text.test.mjs",
    "tests/unit/mail-rows-neutralise-hostile-text.test.mjs",
  ]) {
    const source = readFileSync(resolve(WEB_ROOT, rel), "utf8");
    const hits = source.match(hostile) ?? [];
    assert.deepEqual(
      hits,
      [],
      `${rel} contains ${hits.length} literal control character(s) — spell them \\uXXXX`,
    );
  }
});
