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
 * THE CENSUS BELOW IS THE SOURCE OF TRUTH, AND THAT DIRECTION IS THE POINT.
 * It carries one row per code point this fix has ruled on, each with a
 * disposition and the reason for it.
 *
 * WHAT WAS WRONG WITH WHAT IT REPLACED, said accurately because the census's
 * whole claim is about accuracy. `EXPECTED_SET` was NOT a copy of the module —
 * it was transcribed from #424's prose, so the two lists could genuinely
 * disagree, and the per-member render cases, the over-match sweep and the
 * source scan's positive control all had real teeth. Every one of those is
 * still here. Its three actual defects were narrower: it was a FROZEN ARTIFACT
 * (an anchor to a set someone chose once), `length === 13` PUNISHED HARDENING
 * (covering one more character reddened the suite, so widening the threat model
 * was the blocked act and leaving a hole was the free one), and it could not
 * express a DISPOSITION at all — a code point was either in the list or
 * unmentioned, and "considered and deliberately excluded" had nowhere to live
 * except a comment beside a boundary case.
 *
 * The census fixes exactly those three. Add a `neutralise` row and this file
 * reds, by name, until the module covers it. Add a `passthrough` row and the
 * exclusion is written down with its reason, which is the state U+061C was
 * found missing from.
 *
 * AND THE CENSUS IS ITSELF GRADED, because two lists in one repo maintained by
 * one author stay green through any edit made to both. The universe sweep below
 * asks the ENGINE's Unicode tables for every code point with the
 * `Default_Ignorable_Code_Point` property — the standard's own name for
 * "invisible" — and fails when one of them has no ruling here. Neither list
 * controls that bound, and a Node upgrade that adds a default-ignorable arrives
 * as a red rather than as a silent gap.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { importTsx, markup } from "./helpers/renderTsx.mjs";
import { visibleText } from "./helpers/visibleText.mjs";

const { MailText } = await importTsx("components/mail/MailText.tsx");
const { HOSTILE_CODE_POINTS, HOSTILE_SENTINEL, hostileTextNote, inspectHostileText, safeText } =
  await import("../../lib/security/hostileText.ts");

const cp = (n) => String.fromCodePoint(n);

/** The two overrides #424 measured, plus the pop that terminates one. */
const RLO = cp(0x202e); // RIGHT-TO-LEFT OVERRIDE
const PDF = cp(0x202c); // POP DIRECTIONAL FORMATTING
const ZWSP = cp(0x200b); // ZERO WIDTH SPACE
const WJ = cp(0x2060); // WORD JOINER — the bypass, and outside #424's thirteen
const SENTINEL = cp(0xfffd); // REPLACEMENT CHARACTER — what each one becomes

/**
 * The forged/genuine sender pair, and the invariant that makes it mean
 * something.
 *
 * PROVENANCE. #424 measured this against a real applicant-tracking system's
 * no-reply address. The SHAPE is the measured one — a `no-reply` local part on
 * an employer-facing ATS domain — and the particulars are invented on a domain
 * reserved by RFC 2606, per `docs/TEST_DATA_POLICY.md`. Nothing here can reach
 * a mailbox, and the property under test does not need a routable domain: a
 * forgery rendering identically to a genuine address is just as true of an
 * invented one.
 *
 * GENUINE IS A LITERAL ON PURPOSE. `scripts/check_test_data.py` cannot see an
 * address that is interpolated or assembled — an `@` followed by `{` or a
 * concatenation is invisible to its regex (#647) — so a pair built out of
 * fragments would sail past that gate without it ever having read the domain.
 *
 * FORGED IS DERIVED FROM IT, not written a second time. That is what
 * guarantees the two differ by exactly one invisible character, which is the
 * whole property the strip-versus-sentinel assertion rests on. Two
 * hand-written literals could lose it to a typo and the test would then pass
 * for the wrong reason.
 */
const GENUINE_SENDER = "no-reply@harbourgate.test";
const FORGED_SENDER = GENUINE_SENDER.replace("@", `${ZWSP}@`);
/** The same forgery, spelled with the character the thirteen did not cover. */
const WORD_JOINER_SENDER = GENUINE_SENDER.replace("@", `${WJ}@`);

/**
 * THE CENSUS. Every code point this fix has ruled on, what was decided, and
 * why — and it is what DECIDES, rather than what agrees.
 *
 * Rows are a single `cp` or a `from`/`to` span. Spans exist because the tag
 * block alone is 96 code points and the reserved plane-14 space is 3,600: rows
 * that differ in nothing but their number carry no information, and the reason
 * is the thing a row exists to hold. Every span here is transcribed from
 * Unicode, never read out of the module.
 *
 * The four rules it is held to, all asserted below:
 *   1. every `neutralise` code point is really replaced, really flagged and
 *      really named in `found`;
 *   2. every `passthrough` code point survives byte-identical, with an empty
 *      `found` and no flag;
 *   3. the module covers exactly the `neutralise` rows — stated in that
 *      direction, so the failure reads "the census names X and the module does
 *      not cover it";
 *   4. and the census itself is measured against the engine's Unicode tables,
 *      so it cannot quietly agree with the module about a code point neither
 *      of them has heard of.
 *
 * The rows just outside each block are boundaries, not rulings: a range needs
 * a case sitting ON each edge and one just outside it, or `2060-206F` and
 * `205F-2070` are the same test.
 */
const CENSUS = [
  // ---- neutralised: everything the standard calls default-ignorable, less
  //      the three exclusions below ----------------------------------------
  {
    cp: 0x00ad,
    name: "SOFT HYPHEN",
    disposition: "neutralise",
    why: "zero advance width except at a line break. Its hyphenation-hint use is argued in the header, and the base rate in real mail headers is UNMEASURED — only synthetic corpora were reachable, so the zero we have is not a measured zero",
  },
  {
    cp: 0x034f,
    name: "COMBINING GRAPHEME JOINER",
    disposition: "neutralise",
    why: "invisible, and it joins nothing a reader can see",
  },
  {
    from: 0x115f,
    to: 0x1160,
    name: "HANGUL CHOSEONG/JUNGSEONG FILLER",
    disposition: "neutralise",
    why: "invisible LETTERS, category Lo: a scan for format characters never finds these",
  },
  {
    from: 0x17b4,
    to: 0x17b5,
    name: "KHMER VOWEL INHERENT AQ and AA",
    disposition: "neutralise",
    why: "invisible in modern rendering, and default-ignorable by declaration",
  },
  {
    from: 0x180b,
    to: 0x180d,
    name: "MONGOLIAN FREE VARIATION SELECTOR ONE to THREE",
    disposition: "neutralise",
    why: "zero width. Neutralised while U+FE00-U+FE0F pass: no emoji path reaches these",
  },
  {
    cp: 0x180e,
    name: "MONGOLIAN VOWEL SEPARATOR",
    disposition: "neutralise",
    why: "class BN and zero width since Unicode 6.3 moved it out of the space separators",
  },
  {
    cp: 0x180f,
    name: "MONGOLIAN FREE VARIATION SELECTOR FOUR",
    disposition: "neutralise",
    why: "zero width; the same ruling as its three siblings",
  },
  {
    from: 0x200b,
    to: 0x200d,
    name: "ZERO WIDTH SPACE, NON-JOINER, JOINER",
    disposition: "neutralise",
    why: "zero advance width; U+200B is the one #424 measured inside a forged sender",
  },
  {
    from: 0x202a,
    to: 0x202e,
    name: "the deprecated bidi embeddings and overrides",
    disposition: "neutralise",
    why: "LRE, RLE, PDF, LRO, RLO; U+202E renders `gpj.exe` as `exe.jpg`",
  },
  {
    cp: 0x2060,
    name: "WORD JOINER",
    disposition: "neutralise",
    why: "THE BYPASS: zero width, class BN, interchangeable with the covered U+FEFF, and a review forged a sender with it",
  },
  {
    from: 0x2061,
    to: 0x2064,
    name: "the invisible mathematical operators",
    disposition: "neutralise",
    why: "FUNCTION APPLICATION, INVISIBLE TIMES, INVISIBLE SEPARATOR, INVISIBLE PLUS; zero width, class BN",
  },
  {
    cp: 0x2065,
    name: "(reserved)",
    disposition: "neutralise",
    why: "reserved and default-ignorable: invisible by declaration, with nothing assigned to it",
  },
  {
    from: 0x2066,
    to: 0x2069,
    name: "the modern bidi isolates",
    disposition: "neutralise",
    why: "LRI, RLI, FSI, PDI: the deprecated overrides' power in the current spelling",
  },
  {
    from: 0x206a,
    to: 0x206f,
    name: "the deprecated format controls",
    disposition: "neutralise",
    why: "the symmetric-swapping and Arabic-shaping switches and the digit-shape selectors",
  },
  {
    cp: 0x3164,
    name: "HANGUL FILLER",
    disposition: "neutralise",
    why: "the classic invisible-letter spoofer: a letter to a validator, blank to a reader",
  },
  {
    cp: 0xfeff,
    name: "ZERO WIDTH NO-BREAK SPACE",
    disposition: "neutralise",
    why: "the BOM anywhere but the start of a stream; zero advance width",
  },
  {
    cp: 0xffa0,
    name: "HALFWIDTH HANGUL FILLER",
    disposition: "neutralise",
    why: "U+3164's other half, and the same spoof",
  },
  {
    from: 0xfff0,
    to: 0xfff8,
    name: "(reserved)",
    disposition: "neutralise",
    why: "reserved and default-ignorable",
  },
  {
    from: 0x1bca0,
    to: 0x1bca3,
    name: "the Duployan shorthand format controls",
    disposition: "neutralise",
    why: "invisible format characters. RULED HERE rather than in the brief: the sweep surfaced them and the module's stated rule decides them",
  },
  {
    from: 0x1d173,
    to: 0x1d17a,
    name: "the musical-notation format controls",
    disposition: "neutralise",
    why: "beams, slurs and phrases, all invisible. Ruled here for the same reason as U+1BCA0-U+1BCA3",
  },
  {
    cp: 0xe0000,
    name: "(reserved)",
    disposition: "neutralise",
    why: "reserved plane-14 space, default-ignorable",
  },
  {
    cp: 0xe0001,
    name: "LANGUAGE TAG",
    disposition: "neutralise",
    why: "deprecated and invisible, and above the BMP, which a \\uXXXX class cannot express",
  },
  {
    from: 0xe0002,
    to: 0xe001f,
    name: "(reserved)",
    disposition: "neutralise",
    why: "reserved plane-14 space, default-ignorable",
  },
  {
    from: 0xe0020,
    to: 0xe007f,
    name: "the tag block",
    disposition: "neutralise",
    why: "an invisible mirror of printable ASCII, and what emoji flag sequences are built from. Base rate in real mail headers UNMEASURED, same as U+00AD: revisit this disposition first if it ever turns out common",
  },
  {
    from: 0xe0080,
    to: 0xe00ff,
    name: "(reserved)",
    disposition: "neutralise",
    why: "reserved plane-14 space, default-ignorable",
  },
  {
    from: 0xe01f0,
    to: 0xe0fff,
    name: "(reserved)",
    disposition: "neutralise",
    why: "the rest of plane 14, reserved and default-ignorable",
  },
  // ---- passed through: the three declared exclusions. Each is a TRADE with a
  //      residual, stated in the module's header and repeated here in short --
  {
    cp: 0x061c,
    name: "ARABIC LETTER MARK",
    disposition: "passthrough",
    why: "an implicit mark: it cannot reverse a run. It DOES meet attack 2 (byte-different, pixel-identical) and the exclusion accepts that residual. Declared because a review found it undeclared",
  },
  {
    from: 0x200e,
    to: 0x200f,
    name: "LEFT-TO-RIGHT MARK and RIGHT-TO-LEFT MARK",
    disposition: "passthrough",
    why: "implicit marks that mail clients inject into legitimate Hebrew and Arabic subjects; neutralising them would deface ordinary RTL mail",
  },
  {
    from: 0xfe00,
    to: 0xfe0f,
    name: "VARIATION SELECTOR-1 to -16",
    disposition: "passthrough",
    why: "U+FE0F is emoji presentation, so this block reaches ordinary subjects. RESIDUAL: a selector chain can smuggle data invisibly",
  },
  {
    from: 0xe0100,
    to: 0xe01ef,
    name: "VARIATION SELECTOR-17 to -256",
    disposition: "passthrough",
    why: "the same trade and the same residual as U+FE00-U+FE0F",
  },
  // ---- passed through: the boundaries. None of these is default-ignorable,
  //      which is what makes them evidence that the ranges do not over-reach --
  {
    cp: 0x00ac,
    name: "NOT SIGN",
    disposition: "passthrough",
    why: "one below the soft hyphen",
  },
  {
    cp: 0x00ae,
    name: "REGISTERED SIGN",
    disposition: "passthrough",
    why: "one above it, and it appears in real company names",
  },
  {
    cp: 0x034e,
    name: "the combining mark below U+034F",
    disposition: "passthrough",
    why: "one below the grapheme joiner",
  },
  {
    cp: 0x0350,
    name: "the combining mark above U+034F",
    disposition: "passthrough",
    why: "one above it",
  },
  {
    cp: 0x115e,
    name: "the Hangul jamo below the fillers",
    disposition: "passthrough",
    why: "one below U+115F",
  },
  {
    cp: 0x1161,
    name: "HANGUL JUNGSEONG A",
    disposition: "passthrough",
    why: "one above U+1160, and a real letter",
  },
  {
    cp: 0x17b3,
    name: "the Khmer vowel below U+17B4",
    disposition: "passthrough",
    why: "one below the inherent vowels",
  },
  {
    cp: 0x17b6,
    name: "KHMER VOWEL SIGN AA",
    disposition: "passthrough",
    why: "one above them, and visible",
  },
  {
    cp: 0x180a,
    name: "MONGOLIAN NIRUGU",
    disposition: "passthrough",
    why: "one below the variation selectors, and visible",
  },
  {
    cp: 0x1810,
    name: "MONGOLIAN DIGIT ZERO",
    disposition: "passthrough",
    why: "one above them, and visible",
  },
  {
    cp: 0x200a,
    name: "HAIR SPACE",
    disposition: "passthrough",
    why: "one below the zero-width run, and a real space",
  },
  {
    cp: 0x2010,
    name: "HYPHEN",
    disposition: "passthrough",
    why: "one above U+200F, and visible",
  },
  {
    cp: 0x2029,
    name: "PARAGRAPH SEPARATOR",
    disposition: "passthrough",
    why: "one below the deprecated bidi controls",
  },
  {
    cp: 0x202f,
    name: "NARROW NO-BREAK SPACE",
    disposition: "passthrough",
    why: "one above them, and a real character in French typography",
  },
  {
    cp: 0x205f,
    name: "MEDIUM MATHEMATICAL SPACE",
    disposition: "passthrough",
    why: "one below the word joiner",
  },
  {
    cp: 0x2070,
    name: "SUPERSCRIPT ZERO",
    disposition: "passthrough",
    why: "one above the deprecated format controls. This seat MOVED: U+206A held it until that range grew",
  },
  {
    cp: 0x3163,
    name: "HANGUL LETTER I",
    disposition: "passthrough",
    why: "one below the filler, and visible",
  },
  {
    cp: 0x3165,
    name: "HANGUL LETTER SSANGNIEUN",
    disposition: "passthrough",
    why: "one above it, and visible",
  },
  {
    cp: 0xfdff,
    name: "the Arabic ligature below the variation selectors",
    disposition: "passthrough",
    why: "one below U+FE00",
  },
  {
    cp: 0xfe10,
    name: "PRESENTATION FORM FOR VERTICAL COMMA",
    disposition: "passthrough",
    why: "one above U+FE0F",
  },
  {
    cp: 0xfefe,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "one below the BOM",
  },
  {
    cp: 0xff00,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "one above it",
  },
  {
    cp: 0xff9f,
    name: "the halfwidth katakana mark below U+FFA0",
    disposition: "passthrough",
    why: "one below the halfwidth filler",
  },
  {
    cp: 0xffa1,
    name: "HALFWIDTH HANGUL LETTER KIYEOK",
    disposition: "passthrough",
    why: "one above it, and visible",
  },
  {
    cp: 0xffef,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "one below the reserved default-ignorable run",
  },
  {
    cp: 0xfff9,
    name: "INTERLINEAR ANNOTATION ANCHOR",
    disposition: "passthrough",
    why: "one above it — a FORMAT character that is not default-ignorable, which is why the universe is that property and not category Cf",
  },
  {
    cp: 0x1bc9f,
    name: "the Duployan punctuation below the format controls",
    disposition: "passthrough",
    why: "one below U+1BCA0",
  },
  {
    cp: 0x1bca4,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "one above U+1BCA3",
  },
  {
    cp: 0x1d172,
    name: "the musical combining flag below the format controls",
    disposition: "passthrough",
    why: "one below U+1D173",
  },
  {
    cp: 0x1d17b,
    name: "the musical combining accent above them",
    disposition: "passthrough",
    why: "one above U+1D17A",
  },
  {
    cp: 0xdffff,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "the top of plane 13, one below plane 14's block",
  },
  {
    cp: 0xe1000,
    name: "(unassigned)",
    disposition: "passthrough",
    why: "one above U+E0FFF, where plane 14 stops being ignorable",
  },
];

/** `0x202e` -> `"U+202E"`. The label the module reports and the flag draws. */
const label = (code) => `U+${code.toString(16).toUpperCase().padStart(4, "0")}`;

/** Rows, with singletons and spans in one shape. */
const ROWS = CENSUS.map((row) => ({ ...row, from: row.from ?? row.cp, to: row.to ?? row.cp }));
const NEUTRALISE_ROWS = ROWS.filter((row) => row.disposition === "neutralise");
const PASSTHROUGH_ROWS = ROWS.filter((row) => row.disposition === "passthrough");

const membersOf = (row) => Array.from({ length: row.to - row.from + 1 }, (_, i) => row.from + i);
/** First, middle, last: what gets RENDERED, since 3,915 renders would not pay. */
const samplesOf = (row) => [...new Set([row.from, Math.floor((row.from + row.to) / 2), row.to])];
const span = (row) =>
  row.from === row.to ? label(row.from) : `${label(row.from)}-${label(row.to)}`;

const NEUTRALISE_POINTS = NEUTRALISE_ROWS.flatMap(membersOf);
const CENSUS_POINTS = new Set(ROWS.flatMap(membersOf));

const render = (value) => markup(MailText({ value }));

// ---------------------------------------------------------------------------
// 0. The reading instrument itself.
//
// Every assertion below is a measurement of "what does a person see", taken
// with `visibleText`. An instrument that misreports makes each of them check
// something other than what it says, silently — so it is asserted first, and
// against inputs chosen to break the hand-rolled version it replaced (#424,
// CodeQL js/double-escaping and js/incomplete-multi-character-sanitization).
// ---------------------------------------------------------------------------

test("an escaped entity is reported as the reader sees it, not as a tag", () => {
  // React renders the LITERAL text `&lt;script&gt;` as `&amp;lt;script&amp;gt;`,
  // so what is on the line is `&lt;script&gt;` — punctuation and the letters
  // `lt`, not markup.
  //
  // The helper this replaced unescaped `&amp;` first and `&lt;` second, so
  // `&amp;lt;` collapsed to `&lt;` and then to `<`, and it reported `<script>`
  // — a string no reader ever saw. Any assertion about visible text taken with
  // that instrument was checking a different string than it claimed.
  const literal = "&lt;script&gt; is the text here, not a tag";
  assert.equal(visibleText(markup(MailText({ value: literal }))), literal);
});

test("an attribute value never leaks into the line", () => {
  // A `>` inside a QUOTED attribute does not close the tag — the HTML
  // tokenizer stays in the attribute-value state. `/<[^>]*>/g` cuts there
  // anyway and spills the rest of the attribute into the text it returns:
  // this input came back as `" see\">Payroll"`.
  //
  // NOT REACHABLE FROM A COMPONENT TODAY, and saying so is the point: React
  // escapes `>` to `&gt;` in attribute values, so `renderToStaticMarkup`
  // cannot emit this shape. It is asserted against hand-written markup because
  // the instrument's correctness must not rest on a guarantee made by the
  // thing it measures — and because the helper is shared now, and the next
  // caller may not be React.
  const html = `<p class="x" title="1 hidden character (U+202E) > see">Payroll</p>`;
  assert.equal(visibleText(html), "Payroll");
});

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

test("the forged sender is the genuine one plus one invisible character", () => {
  // Guards the assertion below. If the pair differed in any other byte, "the
  // forged sender did not render as the genuine address" would pass for the
  // wrong reason and a strip would look like a fix.
  assert.equal(FORGED_SENDER.replaceAll(ZWSP, ""), GENUINE_SENDER);
  assert.equal(FORGED_SENDER.length, GENUINE_SENDER.length + 1);
  assert.notEqual(FORGED_SENDER, GENUINE_SENDER);
});

test("the zero-width forgery does NOT render as the genuine address", () => {
  // This is the assertion that forces a sentinel rather than a strip. #424
  // measured a `no-reply` ATS sender with a zero-width space injected before
  // the `@`, rendering to a BYTE-IDENTICAL image of the real address — same
  // SHA-256, both 8,522 bytes. Deleting the ZWSP would leave exactly
  // GENUINE_SENDER, so a "fix" that strips turns a forgery into a perfect
  // impersonation and the row states a falsehood in clean text.
  const text = visibleText(render(FORGED_SENDER));

  assert.equal(text.includes(ZWSP), false, "U+200B reached the rendered text");
  assert.equal(
    text.includes(GENUINE_SENDER),
    false,
    "the forged sender rendered as the genuine address — the sentinel was stripped, not substituted",
  );
  // Exactly what the line must read: the genuine address with a visible mark
  // where the invisible character was. The flag renders first, hence endsWith.
  assert.ok(
    text.endsWith(GENUINE_SENDER.replace("@", `${SENTINEL}@`)),
    `the line does not read as the marked address: ${JSON.stringify(text)}`,
  );
});

test("the WORD JOINER forgery — the bypass a review actually sent — is closed", () => {
  // U+2060 is not one of #424's thirteen and it did not need to be clever: it
  // has zero advance width and bidi class BN, exactly like U+FEFF, which WAS
  // covered, and the two do the same thing to a padded address. Before the set
  // was sourced from `Default_Ignorable_Code_Point` this string rendered
  // through untouched and unflagged — measured, not assumed.
  //
  // It earns its own named test rather than only a census row because it is
  // the reason the census exists, and a name is what a reader sees in CI.
  assert.equal(WORD_JOINER_SENDER.replaceAll(WJ, ""), GENUINE_SENDER);
  assert.equal(WORD_JOINER_SENDER.length, GENUINE_SENDER.length + 1);

  const text = visibleText(render(WORD_JOINER_SENDER));
  assert.equal(text.includes(WJ), false, "U+2060 reached the rendered text");
  assert.equal(
    text.includes(GENUINE_SENDER),
    false,
    "the word-joiner forgery rendered as the genuine address",
  );
  assert.ok(
    text.endsWith(GENUINE_SENDER.replace("@", `${SENTINEL}@`)),
    `the line does not read as the marked address: ${JSON.stringify(text)}`,
  );
  const html = render(WORD_JOINER_SENDER);
  assert.match(html, /data-testid="hidden-character-flag"/, "the bypass was cleaned in silence");
  assert.ok(html.includes("U+2060"), "the flag did not name U+2060");
});

// ---------------------------------------------------------------------------
// 2. The census against the module, the census against the engine, and a case
//    per member. 3,915 code points in 26 rows: a case that only covers U+202E
//    proves nothing whatever about U+2066, and the bypass that prompted this
//    rewrite was precisely a member nobody had a case for.
// ---------------------------------------------------------------------------

test("the census is well formed — nothing ruled twice, every row gives a reason", () => {
  // The census decides what the module must cover, so a row that overlaps
  // another or carries no reason weakens every assertion below it, not just
  // itself.
  const seen = new Set();
  for (const row of ROWS) {
    assert.ok(row.from <= row.to, `${span(row)} runs backwards`);
    for (const code of membersOf(row)) {
      assert.equal(seen.has(code), false, `${label(code)} is ruled on twice`);
      seen.add(code);
    }
    assert.match(row.disposition, /^(neutralise|passthrough)$/, `${span(row)}: bad disposition`);
    assert.ok(row.name.length > 0, `${span(row)} has no name`);
    assert.ok(
      row.why.length > 10,
      `${span(row)} has no reason — a row without one is a transcription, not a ruling`,
    );
  }
  assert.equal(NEUTRALISE_ROWS.length + PASSTHROUGH_ROWS.length, ROWS.length);
});

test("every default-ignorable code point the engine knows has a ruling in the census", () => {
  // THE ONE BOUND NEITHER LIST CONTROLS, and the reason it is here: the census
  // and the module are two lists in one repo with one author, so an edit made
  // to both keeps them green and "the census leads" is true only inside the
  // census's own imagination. `Default_Ignorable_Code_Point` is the standard's
  // own name for "a renderer that does not know this should draw NOTHING", and
  // the engine's tables are outside both lists. A default-ignorable arriving
  // with a Node upgrade lands here as a red instead of as a silent gap.
  const DEFAULT_IGNORABLE = /\p{Default_Ignorable_Code_Point}/u;

  // Controls first, both directions. A property escape that matched nothing —
  // or everything — would report this sweep clean either way.
  assert.equal(DEFAULT_IGNORABLE.test(cp(0x00ad)), true, "the property matches nothing at all");
  assert.equal(DEFAULT_IGNORABLE.test("a"), false, "the property matches everything");

  const unruled = [];
  let counted = 0;
  for (let code = 0; code <= 0x10ffff; code++) {
    if (code >= 0xd800 && code <= 0xdfff) continue; // a lone surrogate is not a character
    if (!DEFAULT_IGNORABLE.test(cp(code))) continue;
    counted++;
    if (!CENSUS_POINTS.has(code)) unruled.push(code);
  }

  assert.deepEqual(
    unruled.slice(0, 8).map(label),
    [],
    `the engine knows ${unruled.length} default-ignorable code point(s) the census has not ruled ` +
      `on — first: ${unruled.slice(0, 8).map(label).join(", ")}. Add a row with a disposition and ` +
      "a reason; an invisible character nobody ruled on is how U+2060 got through.",
  );

  // And the count itself, taken from the engine rather than from either list.
  assert.equal(
    counted,
    4174,
    `the engine now reports ${counted} default-ignorable code points, not 4,174 (this run: ` +
      `Unicode ${process.versions.unicode}). The tables moved. Rule on the difference in the ` +
      "census — do not just update this number.",
  );
});

test("the module covers every code point the census marks for neutralising", () => {
  // THE DIRECTION IS THE POINT. The census names what must be neutralised and
  // the module is measured against it, so adding a `neutralise` row reds this
  // test, by name, until `HOSTILE_RANGES` and the `HOSTILE` literal both cover
  // it. That is what makes widening the threat model the deliberate act rather
  // than the blocked one — under the assertion this replaced, hardening the
  // module was what broke the suite.
  const covered = new Set(HOSTILE_CODE_POINTS.map((c) => c.codePointAt(0)));
  const missing = NEUTRALISE_POINTS.filter((code) => !covered.has(code));
  assert.deepEqual(
    missing.slice(0, 8).map(label),
    [],
    `the census names ${missing.length} code point(s) the module does not cover — first: ` +
      `${missing.slice(0, 8).map(label).join(", ")}. Add them to HOSTILE_RANGES and to the ` +
      "HOSTILE range literal in lib/security/hostileText.ts.",
  );
  // Deliberately ONE direction. The reverse — a code point the module cleans
  // that the census has not ruled on — is the next test's job, and asserting
  // set equality here would make both tests red for either defect and cost the
  // attribution that makes a failure readable.
});

test("the module neutralises nothing the census has not ruled on", () => {
  // The other direction, worded the other way round on purpose: a code point
  // the code cleans that the census has not decided anything about is an
  // undeclared decision, which is the shape U+061C was found in.
  const named = new Set(NEUTRALISE_POINTS);
  const undeclared = HOSTILE_CODE_POINTS.map((c) => c.codePointAt(0)).filter((c) => !named.has(c));
  assert.deepEqual(
    undeclared.slice(0, 8).map(label),
    [],
    `the module neutralises ${undeclared.length} code point(s) the census does not name for it — ` +
      `first: ${undeclared.slice(0, 8).map(label).join(", ")}. Add a row saying why, or stop ` +
      "neutralising it.",
  );
});

for (const row of NEUTRALISE_ROWS) {
  test(`${span(row)} ${row.name} is neutralised — ${row.why}`, () => {
    // (a) EVERY member of the row, through the module itself. This is the case
    //     per member the module's header asks for, and it is cheap.
    for (const code of membersOf(row)) {
      const { text, found } = inspectHostileText(`a${cp(code)}b`);
      assert.equal(text, `a${SENTINEL}b`, `${label(code)} was not replaced`);
      // By its OWN code point. For anything above the BMP this is what the
      // regex's `u` flag buys: without it the replace callback receives a lone
      // surrogate and the label reads U+DB40.
      assert.deepEqual(found, [label(code)], `${label(code)} was misreported in found`);
    }

    // (b) the edges and the middle, RENDERED — because "the function returns
    //     the right string" is not the claim; "the screen cannot lie" is. All
    //     3,915 renders would cost more than they prove, so the row's edges
    //     stand for it and the module-level walk above covers the interior.
    for (const code of samplesOf(row)) {
      const html = render(`Offer${cp(code)} from Acme`);
      const text = visibleText(html);
      assert.equal(text.includes(cp(code)), false, `${label(code)} reached the rendered text`);
      assert.ok(
        text.endsWith(`Offer${SENTINEL} from Acme`),
        `${label(code)}: the honest text around it did not survive: ${JSON.stringify(text)}`,
      );
      // And the row says so — neutralising in silence is the half that gets skipped.
      assert.match(
        html,
        /data-testid="hidden-character-flag"/,
        `${label(code)} was cleaned without a flag`,
      );
      assert.ok(html.includes(label(code)), `the flag did not name ${label(code)}`);
    }
  });
}

test("the range literal and the exported ranges cannot drift apart", () => {
  // Both directions, and note what this does and does not prove:
  // `HOSTILE_CODE_POINTS` is DERIVED from `HOSTILE_RANGES`, so this compares
  // the ranges to the regex — two artifacts written by hand and separately,
  // which is a real check — and says nothing about whether the ranges are the
  // right ones. The census above is what says that.
  for (const character of HOSTILE_CODE_POINTS) {
    assert.equal(
      inspectHostileText(character).found.length,
      1,
      `the regex missed U+${character.codePointAt(0).toString(16)}, which the ranges claim`,
    );
  }

  // Over-match, swept across every code point there is rather than across a
  // neighbourhood: the ranges now reach into three planes, and a sweep aimed
  // at the wrong one reports clean.
  const named = new Set(HOSTILE_CODE_POINTS.map((c) => c.codePointAt(0)));
  const over = [];
  let visited = 0;
  for (let code = 0; code <= 0x10ffff; code++) {
    if (code >= 0xd800 && code <= 0xdfff) continue;
    visited++;
    if (named.has(code)) continue;
    if (inspectHostileText(cp(code)).found.length > 0) over.push(code);
  }
  assert.deepEqual(
    over.slice(0, 8).map(label),
    [],
    `the regex catches ${over.length} code point(s) the ranges do not name — first: ` +
      `${over.slice(0, 8).map(label).join(", ")}`,
  );
  // A floor on the sweep itself: bounds collapsed to nothing would satisfy
  // every assertion above and measure nothing at all.
  assert.equal(visited, 0x110000 - 0x800, `the sweep visited ${visited} code points`);
});

// ---------------------------------------------------------------------------
// 3. The other disposition, which the assertion this file used to carry could
//    not express at all. Every `passthrough` row survives byte-identical and
//    draws no flag.
//
//    Two kinds of row are in here and the difference matters. The BOUNDARIES
//    are ordinary characters just outside each range — evidence the ranges do
//    not over-reach. The EXCLUSIONS are default-ignorable characters the module
//    could neutralise and deliberately does not: the implicit marks (U+200E,
//    U+200F, U+061C) and the variation selectors (U+FE00-U+FE0F,
//    U+E0100-U+E01EF). Each is a trade with a residual, argued in the module's
//    header and named in the row's `why` — an exclusion nobody wrote down is
//    indistinguishable from an oversight, which is exactly the state a review
//    found U+061C in.
// ---------------------------------------------------------------------------

for (const row of PASSTHROUGH_ROWS) {
  test(`${span(row)} ${row.name} passes through untouched — ${row.why}`, () => {
    for (const code of membersOf(row)) {
      const value = `Offer${cp(code)}letter`;
      const { text, found } = inspectHostileText(value);
      assert.equal(text, value, `${label(code)} was altered`);
      assert.deepEqual(found, [], `${label(code)} was reported as hostile`);
    }
    for (const code of samplesOf(row)) {
      const value = `Offer${cp(code)}letter`;
      const html = render(value);
      assert.equal(visibleText(html), value, `${label(code)} did not render as itself`);
      assert.doesNotMatch(html, /hidden-character-flag/, `${label(code)} drew a flag`);
    }
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

test("the astral substitution shortens the string and can never grow it", () => {
  // The tag block is above the BMP, so one tag character is TWO UTF-16 units
  // and the sentinel replacing it is one. The module's header states this
  // rather than claiming a length preservation it does not have: code points
  // are preserved one for one, `.length` drops by one per tag character, and
  // the direction is the safe one — nothing can pad a flag off a line.
  const TAG = cp(0xe0020);
  const value = `a${TAG.repeat(50)}b`;
  const { text, found } = inspectHostileText(value);

  assert.equal(found.length, 50);
  assert.deepEqual([...new Set(found)], ["U+E0020"]);
  assert.equal([...text].length, [...value].length, "a code point was lost or gained");
  assert.equal(text.length, value.length - 50, "each tag character should free one UTF-16 unit");
  assert.ok(text.length < value.length, "the substitution grew the string");
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

test("the flag lists the distinct code points and counts every occurrence", () => {
  const html = render(`${RLO}a${ZWSP}b${ZWSP}c`);
  const note = hostileTextNote(inspectHostileText(`${RLO}a${ZWSP}b${ZWSP}c`).found);

  assert.match(note, /^3 hidden characters \(U\+202E, U\+200B\)/);
  assert.equal(note.includes("U+200B, U+200B"), false, "the note repeated a code point");
  assert.equal(html.includes(note), true, "the note is not on the row");
});

/**
 * The ceiling the note is held to, and where the number comes from: the fixed
 * sentence is about 180 characters, eight labels at their widest are 7
 * characters each (`U+E0FFF`) with ", " between them, and the tail reads
 * ", and 3907 more". 400 leaves room for a count of any width and no room for
 * a list — it is a bound with slack, not a passing measurement written down.
 */
const NOTE_CEILING = 400;

test("the note caps its label list at eight and still reports the true total", () => {
  // Sixteen distinct code points, three occurrences each: more distinct labels
  // than the cap allows, and a count that has to survive the cap.
  const distinct = [
    0x00ad, 0x034f, 0x115f, 0x17b4, 0x180b, 0x200b, 0x202a, 0x2060, 0x3164, 0xfeff, 0xffa0, 0xfff0,
    0x1bca0, 0x1d173, 0xe0001, 0xe0020,
  ];
  const value = `x${distinct.map(cp).join("y").repeat(3)}z`;
  const { found } = inspectHostileText(value);
  assert.equal(found.length, distinct.length * 3, "the fixture did not carry what it claims");

  const note = hostileTextNote(found);
  // (a) THE COUNT IS EXACT. This is the half a length-only test would miss: a
  //     cap that also capped the count would shrink the note and lie.
  assert.match(note, /^48 hidden characters \(/, `the count is wrong: ${note}`);
  // (b) eight labels, and the rest summarised as a number.
  assert.equal((note.match(/U\+[0-9A-F]+/g) ?? []).length, 8, `the list is not capped: ${note}`);
  assert.match(note, /, and 8 more\)/, `the remainder is not summarised: ${note}`);
  // (c) and the whole thing fits where it is drawn.
  assert.ok(note.length < NOTE_CEILING, `the note is ${note.length} characters: ${note}`);
});

test("the worst case the whole set can produce still fits in a title attribute", () => {
  // Not a sample. Every member of the set at once — the input the uncapped form
  // answered with roughly 35 KB, which is the legibility denial the module's
  // header rejects for the expansion form one screen up.
  const everyLabel = HOSTILE_CODE_POINTS.map((c) => label(c.codePointAt(0)));
  const total = everyLabel.length;
  assert.ok(
    total > 1000,
    `the set is ${total} code points — too small to be this test's worst case`,
  );

  // The expected numbers come from the INPUT this test built, not from a
  // constant: what is under test is the cap's arithmetic, and pinning the set's
  // size here would make a deliberate widening red a test about `title` length.
  // The census gates two screens up are what hold the set to a decision.
  const note = hostileTextNote(everyLabel);
  assert.match(
    note,
    new RegExp(`^${total} hidden characters \\(`),
    "the count did not survive the cap",
  );
  assert.match(note, new RegExp(`, and ${total - 8} more\\)`), "the remainder is not summarised");
  assert.ok(note.length < NOTE_CEILING, `the worst case is ${note.length} characters`);
  // The uncapped form for comparison, so the saving is measured rather than
  // asserted: it is what this test exists to prevent coming back.
  assert.ok(everyLabel.join(", ").length > 30000, "the uncapped list is not the size claimed");
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
  const hostile = new RegExp(
    `[${NEUTRALISE_ROWS.map((row) => `\\u{${row.from.toString(16)}}-\\u{${row.to.toString(16)}}`).join("")}]`,
    "gu",
  );

  // POSITIVE CONTROL. A scan that silently matches nothing reports "clean" and
  // "never ran" with the same output, so prove the scanner sees one first.
  assert.equal(`ok${RLO}`.match(hostile).length, 1, "the scanner matches nothing at all");
  // And an ASTRAL one, because matching above the BMP is new capability here:
  // a class built without `u` would match neither the tag block nor anything
  // else it was handed, and would still report every file clean.
  assert.equal(
    `ok${cp(0xe0020)}`.match(hostile).length,
    1,
    "the scanner cannot see a member above the BMP",
  );

  for (const rel of [
    "lib/security/hostileText.ts",
    "components/mail/MailText.tsx",
    "tests/unit/hostile-text.test.mjs",
    "tests/unit/mail-rows-neutralise-hostile-text.test.mjs",
    "tests/unit/helpers/visibleText.mjs",
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
