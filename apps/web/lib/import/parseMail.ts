/**
 * Client-side mail parser for the "Import your mail" feature.
 *
 * Everything in this file is pure, dependency-free JavaScript designed to run
 * IN THE BROWSER: a visitor picks a file, we parse it in their tab, and the
 * text is handed straight to the on-device rules classifier
 * (`lib/demo/rulesLayer.ts`). No byte is ever uploaded — that is the whole
 * privacy point, and it is what lets this run under the app's strict CSP with
 * zero network access.
 *
 * Supported inputs
 * ----------------
 * - **Google Takeout MBOX** (`.mbox`) — Gmail's real export format. A concat
 *   of RFC-822 messages separated by `From ` lines (mboxrd, so body lines that
 *   begin with `From ` are escaped as `>From `).
 * - **`.eml`** — a single RFC-822 message (what "Download message" gives you).
 * - **`.json`** — a simple, forgiving array of `{ subject, from, body, date }`
 *   for anyone who'd rather hand-assemble a batch (or export from a script).
 *
 * The parser is deliberately *pragmatic*, not a full MIME implementation: for
 * classification we only need the Subject, the From, and enough decoded text
 * body to score. We decode the common transfer encodings (base64 /
 * quoted-printable) and RFC-2047 encoded-word headers, pick the first
 * `text/plain` part of a multipart message (falling back to stripped HTML),
 * and bound the work so a multi-gigabyte Takeout export can't hang the tab.
 */

export interface ParsedMessage {
  /**
   * Identity of the MESSAGE, derived from its content — never from where it
   * sat in the file. See `contentId`.
   *
   * IT IS THE REACT KEY THE ROW LIST USES (`ImportMail.tsx`), which is why a
   * positional value here is a defect rather than a cosmetic choice: with
   * `m${i}` as the id, importing a second file handed React the same keys for
   * different mail, so it kept the same `ImportRow` instances mounted and the
   * second file inherited the first file's expanded rows (#426). Unique within
   * one `ParseResult` — `parseMailFile` suffixes any repeat.
   */
  id: string;
  subject: string;
  senderName: string | null;
  senderEmail: string;
  /** Decoded, bounded plain-text body fed to the classifier. */
  body: string;
  /** Short single-line preview for the row. */
  snippet: string;
  /** Raw `Date:` header value, or null. */
  receivedAt: string | null;
}

export type MailFormat = "mbox" | "eml" | "json";

export interface ParseResult {
  format: MailFormat;
  messages: ParsedMessage[];
  /**
   * Messages detected in the file, all of them, whether or not the cap kept
   * them. Not "before the cap was applied": on the mbox path the cap is applied
   * DURING the split now (#810), and this number is counted to EOF alongside it.
   */
  totalFound: number;
  /** True when `totalFound` exceeded the cap and `messages` was trimmed. */
  truncated: boolean;
  /**
   * Detected messages that were inside the cap and still produced nothing,
   * because `parseRfc822` / `parseJsonMessage` returned null.
   *
   * THIS EXISTS BECAUSE THE COUNT USED TO VANISH. `messages.length` was the
   * only number the caller had, so a 400-message batch that lost 7 to
   * unparseable entries reported 400 found and listed 393, with nothing
   * anywhere saying the other 7 had been dropped. Discarding a person's mail
   * silently is bad on its own; it also made the UI's summary sentence false,
   * because "the first 393" describes a prefix and this is not one.
   */
  unreadable: number;
  /**
   * A sentence for the visitor when the file's own structure could not be read
   * unambiguously, or null when it could. Only the mbox path can set it —
   * splitting is the only place this parser has to guess.
   *
   * IT IS NOT AN ERROR AND IT IS NOT A DROP. Every line of the file is still
   * inside one of `messages`; what this says is that the BOUNDARY between two
   * of them was decided rather than read. See `splitMbox`: an mbox whose
   * bodies quote a `From ` line without mboxrd's `>From ` escape used to be
   * split into ten messages, five of them manufactured from body text and
   * rendered beside the real ones with an invented subject, `(unknown sender)`
   * and the same confidence chrome (#426). A parser that cannot tell a
   * separator from a body line should say so, not state a count as fact.
   */
  malformed: string | null;
}

/** Keep the tab responsive: a Takeout mbox can hold tens of thousands of mails. */
export const DEFAULT_MESSAGE_CAP = 400;

/** Upper bound on decoded body length handed to the classifier. */
export const MAX_BODY_CHARS = 8000;
const SNIPPET_CHARS = 180;

/**
 * Upper bound on the subject handed to the classifier. #427.
 *
 * The body has been bounded here since the beginning and the subject was
 * bounded nowhere, on either engine. `classifyWithRules` takes it as its first
 * argument and scans it with every pattern in the set, so the cost is linear in
 * a header nobody bounded: measured on the Python side of the same rules,
 * 100,000 characters costs 232 ms and 1,000,000 costs 2.33 s.
 *
 * NOT A NUMBER CHOSEN HERE. It is `PipelineItemIn.subject`'s `max_length` in
 * `backend/jobtracker/cloud/gmail_oauth.py` — the bound the API has always
 * refused above — which `SampleInbox.tsx` already mirrors for the playground
 * textarea and which the Gmail fetch path now applies at ingest. One quantity,
 * four sites, so a subject cannot classify differently depending on which door
 * it came through.
 */
export const MAX_SUBJECT_CHARS = 2000;

/**
 * And the raw bound, applied BEFORE `decodeEncodedWords`, for the reason
 * `MAX_RAW_BODY_CHARS` below states at length: a bound on a decode's output is
 * not a bound on the decode. A folded RFC 2047 subject is unfolded into one
 * string by `parseHeaders` before it gets here, so "the header is short because
 * lines are short" is not a property this code may assume.
 *
 * WHERE THE NUMBER COMES FROM, AND THE FIRST ANSWER WAS WRONG. This read
 * 8,000, justified as "four raw characters yield three bytes, so 2,000 decoded
 * characters need at most ~2,667 raw ones" — which counts BYTES and then spends
 * them as CHARACTERS, the identical confusion the Python half of this change
 * exists to correct. Measured against `decodeEncodedWords` itself, 8,000 raw
 * characters of RFC 2047 encoded words yield:
 *
 *     B-encoded  ASCII 5706   CJK 2078   emoji 2668
 *     Q-encoded  ASCII 7412   CJK 1412   emoji 1358   <- under the 2,000 bound
 *
 * Quoted-printable spends three raw characters per byte, so a four-byte
 * character costs twelve, and the "three times" headroom was in fact four per
 * cent for B-encoded CJK and NEGATIVE for Q-encoded. The claim that the cut
 * "can never starve the bound it protects" was false for real, well-formed mail.
 *
 * So the budget is the worst case rather than the best: 12 raw characters per
 * decoded character, plus encoded-word wrappers, is 24,000 plus slack. Decoding
 * 32,000 characters is microseconds — the bound exists to stop a 1 MB header
 * costing seconds, and it still does.
 */
const MAX_RAW_SUBJECT_CHARS = 32_000;

/**
 * Upper bound on the RAW text handed to a decoder, applied BEFORE the decode.
 *
 * MAX_BODY_CHARS above is applied to the decode's OUTPUT, which is far too late
 * to be a bound on anything: the whole body is decoded, the whole result is
 * materialised, and then 8,000 characters of it are kept. Measured on this
 * machine with a 33 MB quoted-printable body (`=41` repeated, three raw
 * characters per output character):
 *
 *   before: 888 ms and +334 MB of heap, to produce 8,000 characters
 *
 * `/import` parses on the main thread of an unauthenticated page, so that is
 * blocked tab time bought for nothing.
 *
 * WHERE THE NUMBER COMES FROM. The bound has to be able to produce
 * MAX_BODY_CHARS of text through the most expansive decode we perform. That is
 * base64: 8,000 characters is at most 32,000 UTF-8 bytes, which is ~42,700
 * base64 characters plus line breaks. Quoted-printable is at most 3:1, so
 * 24,000. 256 KB is roughly six times the worst of those, and the surplus is
 * headroom for `text/html`, where most of the input is markup that `stripHtml`
 * discards rather than text it keeps.
 *
 * IT IS APPLIED AT `decodeBody`, WHICH IS THE ONLY PLACE IT CAN GO. That is the
 * single choke point every LEAF part goes through — the top-level body and each
 * part of a multipart alike — so the multipart boundary split still sees the
 * whole body and cannot lose a part. Bounding `extractText`'s input instead
 * would truncate a multipart container mid-part.
 *
 * The cut is not free of consequence and is not pretended to be: a
 * quoted-printable stream cut mid-`=XX` emits one or two literal characters at
 * the tail, and a base64 stream cut mid-quantum has its partial quantum dropped
 * (see `base64ToUtf8`). Both land 256 KB into a body whose first 8,000
 * characters are the only ones the classifier will ever read.
 */
const MAX_RAW_BODY_CHARS = 256_000;

/**
 * Upper bound on a SINGLE RFC-822 message.
 *
 * The `.eml` branch of `parseMailFile` was `raws = [text.trim()]` — the mbox
 * branch has DEFAULT_MESSAGE_CAP and the JSON branch inherits it, and the one
 * format that is defined as "exactly one message" had no bound at all.
 *
 * WHERE THE NUMBER COMES FROM. `.eml` is what "Download message" produces, so
 * the largest honest one is the largest message a mail provider will carry:
 * Gmail's limit is 25 MB of attachments, which is about 34 MB on the wire once
 * base64 has expanded it. 40 MB therefore refuses nothing that could be a real
 * single message.
 *
 * IT IS A REFUSAL, NOT A TRUNCATION. Silently classifying the first N bytes of
 * somebody's mail and reporting it as the message would be worse than saying
 * no — see ParseResult.unreadable for the last time this parser made a count
 * that was not true.
 */
export const MAX_SINGLE_MESSAGE_CHARS = 40_000_000;

/**
 * Thrown by `parseMailFile` for input it refuses rather than fails to read.
 *
 * A distinct type because the two need different words in the UI: "couldn't
 * parse that file" is a guess about the format, and this is a fact about the
 * size. `message` is the sentence shown to the visitor.
 */
export class MailTooLargeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MailTooLargeError";
  }
}

/**
 * Upper bound on the `From:` header. IT IS STILL LOAD-BEARING — this is the
 * only thing standing between a visitor and a frozen tab, and raising it
 * reintroduces the hang.
 *
 * THE QUADRATIC DID NOT GO AWAY, IT MOVED. `parseAngleAddress` is a linear
 * scan now (0.6 ms at N = 32,000, uncapped), so the ANGLE matcher is genuinely
 * fixed. `parseFrom`'s other branch is not: when there is no angle address it
 * falls through to `/[^\s<>@]+@[^\s<>@]+/`, and a run of address-legal
 * characters containing no `@` makes that pattern restart at every position
 * and backtrack over the rest of the run. Measured on this machine, the
 * fallback alone, on the shape issue #406 filed (`"<"×N + "a"×N`, which has no
 * `@` in it) — and identically on a bare `"a"×N`, because the `<` run costs
 * nothing:
 *
 *   N =  4000     25 ms        N = 16000    400 ms
 *   N =  8000    100 ms        N = 32000  1,600 ms      (4x per doubling)
 *
 * So the input the issue was filed about reaches the branch that is still
 * quadratic, and 1024 characters of it costs microseconds only because this
 * cap truncates first. `parse-mail-bounds.test.mjs` measures that through
 * `parseFrom` on fallback-only input rather than asserting it; raising this
 * constant reds it.
 *
 * The cap also does the two smaller jobs it would do anyway: it limits what
 * `decodeEncodedWords` expands, and the length of the name and address a row
 * can carry.
 *
 * 1024 is generous rather than tight. RFC 5322 caps a header line at 998
 * octets, and a real `From:` is a display name plus an address. The cap is
 * applied BEFORE any decoding so an encoded-word bomb cannot expand past it.
 */
const MAX_FROM_CHARS = 1024;

// ---------------------------------------------------------------------------
// Format detection
// ---------------------------------------------------------------------------

/**
 * An mbox opens on a `From ` separator line, with no colon after "From".
 *
 * `\r?` IS LOAD-BEARING AND WAS MISSING. The pattern was `/^From .+\n/`, and
 * in JavaScript `.` excludes carriage returns as well as newlines, so on a
 * CRLF mbox `.+` stopped before the `\r` and the `\n` never matched. Every
 * Takeout export this page exists to read is CRLF. The sniff therefore
 * answered "eml" for every mbox that reached it, and nothing noticed because
 * the sniff only runs for files whose extension is not already known.
 */
const MBOX_OPENER = /^From .+\r?\n/;

export function detectFormat(filename: string, text: string): MailFormat {
  const lower = filename.toLowerCase();
  const head = text.slice(0, 4000).trimStart();

  /**
   * THE CONTENT WINS OVER THE EXTENSION FOR ONE CASE, and it is the case that
   * loses a person's whole export.
   *
   * A Takeout mbox saved or renamed as `.eml` used to be believed. `eml` means
   * "one message", so 400 mails collapsed into a single row: the first mail's
   * headers, and a body containing raw undecoded base64 followed by the entire
   * MIME source of the other 399. Renaming the same bytes to `.mbox` produced
   * 400 correct rows. Nothing warned, because from the parser's point of view
   * one message is a perfectly good answer.
   *
   * The sniff is narrow on purpose: only when the file opens on an mbox `From `
   * separator line, which a lone RFC-822 message does not do (it opens on
   * headers, and `From:` carries a colon that this pattern requires to be
   * absent). So it cannot reclassify a genuine `.eml`.
   */
  if (lower.endsWith(".eml") && MBOX_OPENER.test(head)) return "mbox";

  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".mbox")) return "mbox";
  if (lower.endsWith(".eml")) return "eml";

  // Content sniffing for drag-and-drop or oddly-named files.
  if (head.startsWith("[") || head.startsWith("{")) return "json";
  // An mbox begins with a "From " separator line; a lone .eml usually starts
  // straight into headers.
  if (MBOX_OPENER.test(head)) return "mbox";
  return "eml";
}

// ---------------------------------------------------------------------------
// Header parsing + decoding
// ---------------------------------------------------------------------------

/** Split a raw RFC-822 message into its header block and body. */
function splitHeadersAndBody(raw: string): { headerBlock: string; body: string } {
  const match = raw.match(/\r?\n\r?\n/);
  if (!match || match.index === undefined) {
    return { headerBlock: raw, body: "" };
  }
  return {
    headerBlock: raw.slice(0, match.index),
    body: raw.slice(match.index + match[0].length),
  };
}

/**
 * Parse a header block into a lowercase-keyed map. Folded headers (a
 * continuation line beginning with whitespace) are unfolded onto the header
 * they continue. Only the first occurrence of each header is retained, which
 * is all we consult.
 */
function parseHeaders(headerBlock: string): Map<string, string> {
  const headers = new Map<string, string>();
  const lines = headerBlock.split(/\r?\n/);
  let currentKey: string | null = null;
  let currentVal = "";

  const flush = () => {
    if (currentKey !== null && !headers.has(currentKey)) {
      headers.set(currentKey, currentVal.trim());
    }
    currentKey = null;
    currentVal = "";
  };

  for (const line of lines) {
    if (/^[ \t]/.test(line) && currentKey !== null) {
      // Folded continuation of the current header.
      currentVal += " " + line.trim();
      continue;
    }
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    flush();
    currentKey = line.slice(0, colon).trim().toLowerCase();
    currentVal = line.slice(colon + 1);
  }
  flush();
  return headers;
}

/**
 * @param cut - true when the caller truncated this stream (MAX_RAW_BODY_CHARS),
 *   in which case the trailing partial quantum is dropped.
 *
 *   base64 is read four characters at a time, so a cut stream can end
 *   mid-quantum; `atob` throws on that, and the `catch` below would then hand
 *   the classifier the raw base64 to score. Dropping at most three characters
 *   (two bytes) is the difference between a body and gibberish.
 *
 *   It is conditional because an UNCUT stream that is not a multiple of four is
 *   a different thing — unpadded base64, which `atob` accepts — and trimming
 *   that would silently lose two real bytes off the end of every such body.
 */
function base64ToUtf8(b64: string, cut = false): string {
  try {
    let clean = b64.replace(/\s+/g, "");
    if (cut) clean = clean.slice(0, clean.length - (clean.length % 4));
    const binary = atob(clean);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  } catch {
    return b64;
  }
}

function decodeQuotedPrintable(input: string, isHeader = false): string {
  // Soft line breaks: "=" at end of line.
  let s = input.replace(/=\r?\n/g, "");
  if (isHeader) s = s.replace(/_/g, " ");
  const bytes: number[] = [];
  const encoder = new TextEncoder(); // hoisted: one per call, not one per char
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "=" && i + 2 < s.length && /[0-9A-Fa-f]{2}/.test(s.slice(i + 1, i + 3))) {
      bytes.push(parseInt(s.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      // Push the UTF-8 bytes of this character.
      for (const b of encoder.encode(ch)) bytes.push(b);
    }
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(Uint8Array.from(bytes));
}

/** Decode RFC-2047 encoded words (`=?utf-8?B?...?=` / `=?utf-8?Q?...?=`). */
export function decodeEncodedWords(value: string): string {
  if (!value.includes("=?")) return value;
  return value.replace(
    /=\?[^?]+\?([BbQq])\?([^?]*)\?=/g,
    (_m, enc: string, data: string) => {
      if (enc.toUpperCase() === "B") return base64ToUtf8(data);
      return decodeQuotedPrintable(data, true);
    },
  );
}

/** JavaScript's `\s`, and the four characters its `.` refuses to match. */
const WHITESPACE = /\s/;
const LINE_TERMINATOR = /[\n\r\u2028\u2029]/;

/**
 * Split a header value into `name` + `<address>`, in one linear scan.
 *
 * THIS REPLACES `/^(.*?)<([^>]+)>\s*$/`, WHICH BACKTRACKED QUADRATICALLY. A
 * lazy `.*?` in front of a literal that never satisfies the anchor makes the
 * engine restart at every position, so a value of N unmatched `<` characters
 * costs O(N²). Measured on this machine, the regex alone, on `"<"×N + "a"×N`:
 *
 *   N =  2000     18 ms        N = 16000   1,144 ms
 *   N =  4000     71 ms        N = 32000   4,569 ms
 *   N =  8000    285 ms        N = 64000  18,176 ms
 *
 * Four times the cost per doubling, which is the quadratic in the open.
 *
 * A 1024-character cap on the caller (MAX_FROM_CHARS) already held `parseFrom`
 * itself to about 2 ms, and that cap is staying — and it is still load-bearing
 * for a DIFFERENT reason, which the constant's own doc comment now states:
 * `parseFrom`'s bare-address fallback is quadratic too and was not touched
 * here. What this scan fixes is that a caller of the ANGLE matcher — a
 * `Reply-To`, a `Sender`, a future header — no longer pays O(N²) for it with
 * nothing in the code to say why it must not.
 *
 * THE SCAN IS THE REGEX'S SEMANTICS, NOT A SIMPLIFICATION OF THEM, and the
 * difference matters on real mail:
 *
 * - `\s*$` after the closing `>`: the `>` must be the last NON-SPACE character.
 *   `"<a@b.test> trailing"` is not an angle address and falls through to the
 *   bare-address branch exactly as before.
 * - `[^>]+` cannot span a `>`, so the opening `<` must sit after the last `>`
 *   that precedes the closing one. That is what makes
 *   `"Name <a@b.test> <c@d.test>"` yield the name `Name <a@b.test>`.
 * - The lazy `.*?` then takes the FIRST `<` after that point, which is why
 *   `"a<b<c@d.test>"` yields the address `b<c@d.test` and not `c@d.test`.
 * - `[^>]+` is one-or-more, so `"Name <>"` does not match.
 * - `.` excludes line terminators and the pattern is anchored at `^`, so a
 *   newline anywhere BEFORE the `<` means no match — while the address itself,
 *   matched by `[^>]+`, may contain one. This one is unreachable through
 *   `parseFrom` (`parseHeaders` unfolds continuations onto one line before it
 *   ever gets here) and is reproduced anyway, because "unreachable today" is
 *   not a property a shared helper should quietly depend on.
 *
 * `parse-mail-from-scan.test.mjs` pins all of it against a table taken from the
 * old regex, and fuzzes the two implementations against each other over 20,000
 * random strings. The last two bullets are there BECAUSE of that fuzz: the
 * first draft of this scan got both wrong.
 *
 * EXPORTED SO ITS COST CAN BE MEASURED WITHOUT THE CAP IN FRONT OF IT. A timing
 * test that went through `parseFrom` would pass identically with the regex
 * restored, because MAX_FROM_CHARS holds that path to ~2 ms either way — a
 * check that cannot fail. This is the entry point that can.
 *
 * Returns null for "not an angle address", which is the regex's no-match.
 */
export function parseAngleAddress(value: string): { name: string; email: string } | null {
  // `\s*$`: walk back over trailing whitespace to the character that has to be
  // the `>`. A backward scan rather than `trimEnd()` so nothing is allocated.
  let gt = value.length - 1;
  while (gt >= 0 && WHITESPACE.test(value[gt])) gt--;
  if (gt < 1 || value[gt] !== ">") return null;

  const prevGt = value.lastIndexOf(">", gt - 1);
  const lt = value.indexOf("<", prevGt + 1);
  // `lt >= gt - 1` covers both "no `<` before the `>`" and an empty address.
  if (lt === -1 || lt >= gt - 1) return null;

  const name = value.slice(0, lt);
  // `^(.*?)` cannot cross a line terminator.
  if (LINE_TERMINATOR.test(name)) return null;

  return { name, email: value.slice(lt + 1, gt) };
}

/** Parse a `From:` value into a display name + bare email address. */
export function parseFrom(value: string): { name: string | null; email: string } {
  // Bound FIRST — see MAX_FROM_CHARS. Nothing upstream limits a header, and
  // `decodeEncodedWords` can expand what it is given.
  const decoded = decodeEncodedWords(value.slice(0, MAX_FROM_CHARS)).trim();
  const angle = parseAngleAddress(decoded);
  if (angle) {
    const name = angle.name.trim().replace(/^"(.*)"$/, "$1").trim();
    return { name: name || null, email: angle.email.trim().toLowerCase() };
  }
  const bare = decoded.match(/[^\s<>@]+@[^\s<>@]+/);
  return { name: null, email: bare ? bare[0].toLowerCase() : decoded.toLowerCase() };
}

// ---------------------------------------------------------------------------
// Body extraction
// ---------------------------------------------------------------------------

/**
 * Named character references we resolve. Deliberately short: the five HTML
 * predefined names, the spaces, and the punctuation that actually turns up in
 * recruiting mail. Everything else is reachable numerically, and an unknown
 * `&name;` is left exactly as written rather than guessed at.
 */
/*
 * `Object.create(null)`, NOT an object literal, and the same for RAW_TEXT_END
 * below. A literal inherits from `Object.prototype`, so a lookup keyed on
 * attacker-supplied text can walk off the table and return a prototype member.
 *
 * Exactly one key reaches it, and only one is needed: both call sites
 * lower-case the key first, and `constructor` is the sole all-lowercase member
 * of `Object.prototype`. `toString`, `valueOf` and `hasOwnProperty` are safe by
 * accident of their casing, which is not a property to rely on.
 *
 * Measured before the fix, on the public `/import` path:
 *   stripHtml("price &constructor; end")
 *     -> "price function Object() { [native code] } end"
 *   stripHtml("A<constructor>x</constructor>B")
 *     -> TypeError: rawEnd.exec is not a function
 * The first put JavaScript source into the text the classifier scores. The
 * second threw, and `ImportMail.ingest` wraps the whole parse in one
 * try/catch, so ONE such message discarded an entire mbox — 400 mails in,
 * "Couldn't parse that file" out.
 */
const NAMED_ENTITIES: Record<string, string> = Object.assign(Object.create(null), {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  ensp: " ",
  emsp: " ",
  thinsp: " ",
  shy: "",
  ndash: "\u2013",
  mdash: "\u2014",
  hellip: "\u2026",
  lsquo: "\u2018",
  rsquo: "\u2019",
  ldquo: "\u201c",
  rdquo: "\u201d",
  bull: "\u2022",
  middot: "\u00b7",
  copy: "\u00a9",
  reg: "\u00ae",
  trade: "\u2122",
});

const ENTITY = /&(#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{0,30});/g;

/**
 * Decode character references in ONE pass.
 *
 * This is the whole point of the function: a chain of sequential replacements
 * re-reads its own output, so `&amp;` → `&` first turns `&amp;lt;` into `&lt;`
 * into `<` — text that was escaped precisely so it would NOT be markup comes
 * out as markup (CodeQL `js/double-escaping`). One regex, each reference
 * resolved once and never revisited, makes that unrepresentable.
 */
function decodeEntities(text: string): string {
  return text.replace(ENTITY, (whole, ref: string) => {
    if (ref[0] === "#") {
      const hex = ref[1] === "x" || ref[1] === "X";
      const cp = parseInt(hex ? ref.slice(2) : ref.slice(1), hex ? 16 : 10);
      // Reject NUL, surrogates and out-of-range values rather than throwing.
      if (!cp || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return whole;
      return String.fromCodePoint(cp);
    }
    return NAMED_ENTITIES[ref.toLowerCase()] ?? whole;
  });
}

/** Elements whose content is data, not text: dropped along with the element. */
const RAW_TEXT_END: Record<string, RegExp> = Object.assign(Object.create(null), {
  // HTML ends a raw-text element at `</name` followed by whitespace, `/` or
  // `>` — `</script >` and `</script foo=bar>` close it just as `</script>`
  // does. Matching only the literal `</script>` is CodeQL `js/bad-tag-filter`,
  // and it left the element's contents in the text we score.
  script: /<\/script(?=[\s/>])/gi,
  style: /<\/style(?=[\s/>])/gi,
});

/** `<` + a tag name at `lt`, or null when the `<` is just prose ("3 < 4"). */
const TAG_OPEN = /<(\/?)([a-zA-Z][^\s/>]*)/y;

/** Index just past the `>` that ends the tag opened at `from`, or -1. */
function endOfTag(html: string, from: number): number {
  let quote = "";
  for (let i = from; i < html.length; i++) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === ">") {
      return i + 1;
    }
  }
  return -1;
}

/**
 * Reduce an HTML body to the plain text the classifier scores.
 *
 * A hand-rolled scanner rather than a chain of regexes, and rather than
 * `DOMParser`, on purpose. `DOMParser` would be the more correct parser, but
 * it exists only on a window: not in a worker (where the file's own "keep the
 * tab responsive" bound points), not under SSR, and not in `node --test` —
 * which would leave the shipped path covered by nothing but a fallback. This
 * module's contract is pure, dependency-free JavaScript that runs anywhere, so
 * the scanner is what gets tested and what ships. It is immune to the tag
 * shapes a regex misses: an attribute value holding `>`, a comment holding
 * `>`, and every legal spelling of an end tag.
 *
 * Every removed construct becomes one space, so `a<br>b` stays two words.
 * Entities are decoded only AFTER markup is gone, so a decoded `<` can never
 * be re-read as a tag.
 */
export function stripHtml(html: string): string {
  let out = "";
  let i = 0;

  while (i < html.length) {
    const lt = html.indexOf("<", i);
    if (lt === -1) {
      out += html.slice(i);
      break;
    }
    out += html.slice(i, lt);

    if (html.startsWith("<!--", lt)) {
      const end = html.indexOf("-->", lt + 4);
      out += " ";
      i = end === -1 ? html.length : end + 3;
      continue;
    }

    TAG_OPEN.lastIndex = lt;
    const open = TAG_OPEN.exec(html);
    if (!open) {
      // `<!doctype…>`, `<?…>`, `</ …>`: bogus comments, swallowed to the
      // next `>`. Anything else is a literal `<` in prose.
      const next = html[lt + 1];
      if (next === "!" || next === "?" || next === "/") {
        const end = html.indexOf(">", lt + 1);
        out += " ";
        i = end === -1 ? html.length : end + 1;
      } else {
        out += "<";
        i = lt + 1;
      }
      continue;
    }

    const end = endOfTag(html, TAG_OPEN.lastIndex);
    if (end === -1) {
      // No closing `>` before EOF — not a tag at all; keep it as text.
      out += html.slice(lt);
      break;
    }
    out += " ";
    i = end;

    const rawEnd = open[1] ? undefined : RAW_TEXT_END[open[2].toLowerCase()];
    if (rawEnd) {
      rawEnd.lastIndex = end;
      const close = rawEnd.exec(html);
      // An unterminated <script>/<style> runs to EOF: its source is data, and
      // spilling it into the body would be the bug this guards against.
      const after = close ? endOfTag(html, close.index + close[0].length) : -1;
      i = close ? (after === -1 ? html.length : after) : html.length;
    }
  }

  return decodeEntities(out).replace(/\s+/g, " ").trim();
}

function decodeBody(body: string, encoding: string | undefined, isHtml: boolean): string {
  const enc = (encoding ?? "").toLowerCase();

  // BOUND BEFORE THE WORK, NOT AFTER IT. See MAX_RAW_BODY_CHARS: the caller's
  // `.slice(0, MAX_BODY_CHARS)` runs on the decode's output, so without this
  // line the whole body is decoded and the whole result allocated in order to
  // keep 8,000 characters of it.
  const cut = body.length > MAX_RAW_BODY_CHARS;
  const raw = cut ? body.slice(0, MAX_RAW_BODY_CHARS) : body;

  let text = raw;
  if (enc === "base64") text = base64ToUtf8(raw, cut);
  else if (enc === "quoted-printable") text = decodeQuotedPrintable(raw);
  return isHtml ? stripHtml(text) : text;
}

/** Raw (original-case) Content-Type value — MIME boundaries are case-sensitive. */
function rawContentType(headers: Map<string, string>): string {
  return headers.get("content-type") ?? "text/plain";
}

function contentType(headers: Map<string, string>): string {
  return rawContentType(headers).toLowerCase();
}

/**
 * Extract the multipart boundary from the ORIGINAL-case Content-Type value.
 *
 * The boundary delimiter in the body is case-sensitive (RFC 2046 §5.1.1), so it
 * must never be lowercased. Many real providers emit mixed-case boundaries
 * (Apple Mail `Apple-Mail=_…`, Outlook `_000_…`, `NextPart_…`); lowercasing the
 * boundary would make `--Apple-Mail=…` fail to match `--apple-mail=…`, so the
 * split silently no-ops and the raw MIME — both parts, boundary lines, and
 * undecoded transfer-encoding — leaks into the "body" handed to the classifier.
 */
function boundaryOf(ctRaw: string): string | null {
  const m = ctRaw.match(/boundary="?([^";]+)"?/i);
  return m ? m[1] : null;
}

/**
 * Reduce one message (its top-level headers + raw body) to bounded plain text.
 * For multipart bodies we recurse into the first usable part, preferring
 * `text/plain` and falling back to stripped `text/html`.
 */
function extractText(headers: Map<string, string>, body: string, depth = 0): string {
  const ct = contentType(headers);

  if (ct.startsWith("multipart/") && depth < 4) {
    const boundary = boundaryOf(rawContentType(headers));
    if (boundary) {
      const parts = body
        .split(new RegExp(`--${boundary.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:--)?\\r?\\n?`))
        .filter((p) => p.trim() !== "");
      let htmlFallback = "";
      for (const part of parts) {
        const { headerBlock, body: partBody } = splitHeadersAndBody(part);
        const partHeaders = parseHeaders(headerBlock);
        const partCt = contentType(partHeaders);
        if (partCt.startsWith("multipart/")) {
          const nested = extractText(partHeaders, partBody, depth + 1);
          if (nested) return nested;
          continue;
        }
        const enc = partHeaders.get("content-transfer-encoding");
        if (partCt.startsWith("text/plain")) {
          return decodeBody(partBody, enc, false);
        }
        if (partCt.startsWith("text/html") && !htmlFallback) {
          htmlFallback = decodeBody(partBody, enc, true);
        }
      }
      if (htmlFallback) return htmlFallback;
    }
  }

  const enc = headers.get("content-transfer-encoding");
  return decodeBody(body, enc, ct.startsWith("text/html"));
}

// ---------------------------------------------------------------------------
// Message parsing
// ---------------------------------------------------------------------------

function collapse(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

// ---------------------------------------------------------------------------
// Message identity
// ---------------------------------------------------------------------------

/**
 * How much of a message is hashed for its id.
 *
 * The hash is a linear walk, so this is a bound on work, not on correctness:
 * two messages agreeing for 8,000 characters and differing after are told
 * apart by the position salt below. 8,000 is comfortably past any real header
 * block — RFC 5322 caps a header LINE at 998 octets — so in practice it covers
 * every header plus the opening of the body.
 */
const MAX_ID_HASH_CHARS = 8000;

/**
 * Longest `Message-ID:` adopted verbatim; anything longer is hashed instead.
 *
 * `/import` is public and unauthenticated, so every byte in that header came
 * from a stranger and a multi-megabyte value would otherwise become a string
 * this parser carries on every row. RFC 5322 gives a message-id no length of
 * its own beyond the 998-octet line cap; 256 is generous against every real
 * one and still bounded. `MAX_FROM_CHARS` is the same reasoning, one header
 * over.
 */
const MAX_MESSAGE_ID_CHARS = 256;

/**
 * 53-bit content hash (cyrb53). Pure, dependency-free and synchronous, which
 * `crypto.subtle` is not — this runs on the main thread of a page under a
 * strict CSP with no network access, and it decides a React key, not a
 * security property.
 */
function hash53(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/**
 * The id of a message, from what it SAYS rather than from where it sat.
 *
 * WHY THIS EXISTS. `parseMailFile` minted `const id = `m${i}``, so the id was
 * the ordinal and `key={item.id}` in `ImportMail` was keying by position under
 * another name. Importing a second file then handed React identical keys for
 * different mail: the `ImportRow` instances were reused rather than remounted
 * and rows 1 and 3 stayed expanded over somebody else's messages (#426). The
 * issue had already been "fixed" by keying on the id, which is why the
 * remedy has to be checked at THIS end.
 *
 * `Message-ID:` FIRST, because that is the identifier mail already has: RFC
 * 5322 §3.6.4 makes it globally unique, and it is what makes the id survive
 * the same message arriving through a different file or a different export.
 *
 * OTHERWISE A HASH OF THE MESSAGE, PLUS A POSITION SALT. The hash is what
 * makes two different messages different — a scheme that stayed positional
 * cannot pass a cross-file collision test. The salt is only a tie-break for
 * BYTE-IDENTICAL messages in one file, which a mailbox export really does
 * contain, and it is not what carries the identity: two files whose messages
 * differ produce different hashes at every position.
 */
function contentId(messageIdHeader: string | undefined, content: string, salt: string): string {
  const mid = collapse(messageIdHeader ?? "");
  if (mid) return `mid:${mid.length > MAX_MESSAGE_ID_CHARS ? hash53(mid) : mid}`;
  return `h:${hash53(content.slice(0, MAX_ID_HASH_CHARS))}:${salt}`;
}

/**
 * Parse a single raw RFC-822 message into the fields the classifier needs.
 *
 * @param salt - where this message sat in its file, used ONLY to tell
 *   byte-identical messages apart (see `contentId`). It is deliberately not
 *   the id: this parameter used to BE the id, and passing the ordinal in is
 *   how the id became positional in the first place.
 */
export function parseRfc822(raw: string, salt: string): ParsedMessage | null {
  const { headerBlock, body } = splitHeadersAndBody(raw);
  const headers = parseHeaders(headerBlock);

  const subjectRaw = headers.get("subject") ?? "";
  const fromRaw = headers.get("from") ?? "";
  if (!subjectRaw && !fromRaw && !body.trim()) return null;

  // Raw bound first, decoded bound second — see MAX_RAW_SUBJECT_CHARS.
  const subject = decodeEncodedWords(subjectRaw.slice(0, MAX_RAW_SUBJECT_CHARS))
    .trim()
    .slice(0, MAX_SUBJECT_CHARS);
  const { name, email } = parseFrom(fromRaw);

  const fullText = extractText(headers, body).slice(0, MAX_BODY_CHARS);
  const collapsed = collapse(fullText);

  return {
    id: contentId(headers.get("message-id"), raw, salt),
    subject: subject || "(no subject)",
    senderName: name,
    senderEmail: email || "(unknown sender)",
    body: fullText,
    snippet: collapsed.slice(0, SNIPPET_CHARS),
    receivedAt: headers.get("date") ?? null,
  };
}

/** One message as it was found in an mbox. */
export interface MboxChunk {
  /** Raw RFC-822 text of the message, mboxrd `>From ` escapes undone. */
  raw: string;
  /**
   * Where the message starts in the file, counted with ONE character per line
   * ending — the split that produces these does not keep the terminators, so
   * on a CRLF export this is not a byte count. It is strictly increasing and
   * unique per message, which is the whole of what `contentId` asks of it.
   *
   * AND IT STAYS THAT WAY ON PURPOSE. The bounded scan (#810) walks `text` by
   * index, so it has a true character offset in hand and deliberately keeps
   * accumulating this one instead. This number is the `salt` every mbox id is
   * minted from — see `contentId` — so "fixing" it into a byte offset would
   * change every id on every CRLF export, which is every real Takeout file,
   * and buy nothing: nothing reads it as a position into the file.
   */
  offset: number;
}

export interface MboxSplit {
  /**
   * The messages that were MATERIALISED, which is at most `cap` of them and is
   * NOT the file's message count. That is `total`.
   */
  chunks: MboxChunk[];
  /**
   * Every message in the file, counted to EOF and exact.
   *
   * DELIBERATELY NOT `chunks.length` (#810). `ImportMail` publishes this to the
   * visitor as fact — "{totalFound} messages found" — while `chunks` is bounded
   * by the cap, so a split that stops materialising early still has to count
   * all the way. See `splitMbox` for why the count survives the bound.
   */
  total: number;
  /** See `ParseResult.malformed`, which this is the only source of. */
  malformed: string | null;
}

/**
 * What the line after a separator has to look like: a header field name and
 * its colon (RFC 5322 §3.6 field names are printable ASCII without a colon;
 * this is the narrower shape every real header uses).
 *
 * STICKY RATHER THAN `^`-ANCHORED, because the scan below never cuts a line
 * out of the file to test it — it points `lastIndex` at the line's first
 * character instead (#810). No character this pattern can match is `\r` or
 * `\n`, so a sticky match cannot run past the line it started on, and the two
 * forms therefore accept exactly the same lines.
 */
const HEADER_LINE = /[A-Za-z][A-Za-z0-9-]*:/y;

/**
 * How far into a block this looks for an envelope header.
 *
 * A bound is needed because a block with no blank line in it is ALL header
 * block, and this question has to be answered for every chunk in the file
 * including the ones past DEFAULT_MESSAGE_CAP that will never be parsed — the
 * cap bounds what the split MATERIALISES, and it is this predicate that makes
 * `MboxSplit.total` exact, so the count cannot be had without it (#810). Real
 * mail puts `From:` and `Date:` in the first few lines; RFC 5322 caps a header
 * line at 998 octets, so 8,000 is several headers deep and still constant work
 * per chunk.
 */
const MAX_ENVELOPE_SCAN_CHARS = 8000;

/**
 * True when a block carries the envelope a message has and body text does not.
 *
 * A SCAN OF THE HEADER BLOCK, NOT A PARSE OF IT. This was
 * `parseHeaders(splitHeadersAndBody(raw).headerBlock)` and `.has(…)`, which is
 * the same answer and builds a Map plus a substring per header line — for
 * EVERY chunk in the file, because the re-join has to happen before
 * `totalFound` is counted. Measured on 100,000 minimal messages (19.9 MB),
 * min of three, against the same file before that change:
 *
 *     split only, before that change    62 ms
 *     parseHeaders per chunk           119 ms   (1.82x)
 *     this scan                         77 ms   (1.23x)
 *
 * The cap does not spare this — see MAX_ENVELOPE_SCAN_CHARS — and a Takeout
 * export runs to 786,800 messages, which is 7.9x this fixture. So the two
 * implementations are about 0.3 s of blocked tab time apart on the largest
 * input this page accepts, and what is left over the old split is about 0.1 s.
 *
 * The search is bounded to the header block rather than run over the whole
 * chunk: a quoted `From:` line in a BODY is exactly the text this predicate
 * exists to recognise as body, and matching it would leave the phantom row in
 * place. `^` under `m` sits after the `\n` of a CRLF pair, so this reads a
 * CRLF export the same way.
 *
 * IT IS THE FALLBACK NOW, NOT THE FIRST TRY (#810). `splitMbox` answers the
 * same question from the file's own indices for any block whose rendered lines
 * begin `From:` or `Date:` — which is every message in a real export — and
 * only builds the head string this reads when that pre-filter came back empty.
 * See ENVELOPE_FIELD for why the pre-filter can never say yes where this would
 * have said no.
 */
function carriesAnEnvelope(raw: string): boolean {
  const blank = raw.search(/\r?\n\r?\n/);
  const end = blank === -1 ? raw.length : blank;
  return /^(from|date):/im.test(raw.slice(0, Math.min(end, MAX_ENVELOPE_SCAN_CHARS)));
}

/**
 * `carriesAnEnvelope`'s question asked of ONE LINE, so the common case never
 * builds the block (#810).
 *
 * A SOUND PRE-FILTER AND NOT A REPLACEMENT, which is the only property that
 * matters here. `carriesAnEnvelope` runs `/^(from|date):/im` over the head, and
 * under `m` a JavaScript `^` sits after every LineTerminator — including a bare
 * `\r` or a U+2028 that `text.split(/\r?\n/)` does NOT treat as a line ending.
 * So the rendered line starts this is tested at are a SUBSET of the positions
 * that function would try: a hit here is a hit there, always; a miss here may
 * still be a hit there, and is therefore resolved by building the head and
 * calling the real function.
 *
 * Both alternatives are five characters, which is what bounds a match against
 * MAX_ENVELOPE_SCAN_CHARS the way `raw.slice` bounds the real one.
 */
const ENVELOPE_FIELD = /(?:from|date):/iy;
const ENVELOPE_FIELD_CHARS = 5;

/**
 * The whitespace `String.prototype.trim` removes, tested one character at a
 * time.
 *
 * The scan decides "is this line blank" (the mbox separator rule) and "where
 * does this segment's rendered text begin" (`render`'s leading `.trim()`)
 * without cutting the line out of the file, so it needs the predicate as a
 * test on a character rather than as `line.trim() === ""`. This set is JS `\s`
 * exactly — WhiteSpace ∪ LineTerminator — which is the same set `trim` removes,
 * so the two agree on NBSP, U+FEFF and the Unicode space separators as well as
 * on the ASCII five.
 */
function isSpaceCode(code: number): boolean {
  return (
    code === 0x20 ||
    (code >= 0x09 && code <= 0x0d) ||
    code === 0xa0 ||
    code === 0x1680 ||
    (code >= 0x2000 && code <= 0x200a) ||
    code === 0x2028 ||
    code === 0x2029 ||
    code === 0x202f ||
    code === 0x205f ||
    code === 0x3000 ||
    code === 0xfeff
  );
}

/** First non-whitespace character in `text[from, to)`, or -1 when there is none. */
function firstNonSpace(text: string, from: number, to: number): number {
  for (let i = from; i < to; i++) if (!isSpaceCode(text.charCodeAt(i))) return i;
  return -1;
}

/** The sentence `ParseResult.malformed` carries. Each clause only when true. */
function malformedNote(unescaped: number, rejoined: number): string | null {
  if (unescaped === 0 && rejoined === 0) return null;

  const clauses: string[] = [];
  if (unescaped > 0) {
    clauses.push(
      `${unescaped} line${unescaped === 1 ? "" : "s"} beginning “From ” ` +
        `${unescaped === 1 ? "sits" : "sit"} inside a message body without the “>From ” escape an mbox export writes`,
    );
  }
  if (rejoined > 0) {
    clauses.push(
      `${rejoined} block${rejoined === 1 ? "" : "s"} carried no From: or Date: header, so ` +
        `${rejoined === 1 ? "it was" : "they were"} read as part of the message above`,
    );
  }

  return (
    "That file doesn’t read as a clean mbox, so the boundary between messages had to be " +
    `decided rather than read: ${clauses.join(", and ")}. Nothing was dropped — every line is ` +
    "inside one of the messages below — but a message may be split in the wrong place."
  );
}

/**
 * Split an mbox into raw messages. A separator is a line beginning with
 * `From ` that either starts the file or follows a blank line (the standard
 * mbox rule) — this avoids false splits on body lines that merely start with
 * "From ". Body `>From ` escapes (mboxrd) are unescaped.
 *
 * ---------------------------------------------------------------------------
 * AND THAT RULE ALONE INVENTS MESSAGES (#426).
 * ---------------------------------------------------------------------------
 *
 * mboxrd says a body line beginning `From ` is written `>From `, and Google
 * Takeout does escape correctly, so a real export never reaches this. A
 * hand-assembled or re-saved one does, and five messages whose bodies quoted a
 * forwarded header produced ten: `10 messages found` stated as fact, and five
 * phantoms rendered beside the real rows with an invented subject taken from
 * the quoted text, sender `(unknown sender)`, and the same confidence chrome.
 * The row-level claim is the defect — the count is only how you notice.
 *
 * TWO TESTS, because one of them is not enough and it is the prescribed one.
 *
 *   1. The line AFTER a candidate separator has to look like a header. A real
 *      separator is always followed by the message's first header line.
 *
 *   2. A block carrying neither `From:` nor `Date:` is not a message. Test 1
 *      passes happily when the quoted text continues `Subject: …`, which IS
 *      header-shaped — measured, that shape still produced ten rows with test
 *      1 alone — so this is the one that makes the count true. Both headers
 *      have to be absent: real mail has at least one, and plenty of fixtures
 *      here carry `From:` without `Date:`.
 *
 * NOTHING IS DROPPED BY EITHER. A rejected separator stays in the body it came
 * from, and a re-joined block goes back onto the message above it WITH the
 * `From ` line that split it off. The file is reassembled, not trimmed; what
 * changes is that the page stops claiming a message where it only had text.
 * `malformed` says so out loud, and it is null whenever neither test fired —
 * a guard that also fired on the correctly escaped file would measure nothing.
 *
 * ---------------------------------------------------------------------------
 * IT WALKS THE WHOLE FILE AND MATERIALISES `cap` OF IT (#810).
 * ---------------------------------------------------------------------------
 *
 * This opened on `text.split(/\r?\n/)` and then built a `lines: string[]` per
 * segment and a joined, un-escaped, trimmed `raw` per segment — for the whole
 * file, before a cap that only ever keeps 400. The cap worked perfectly on the
 * 400 messages it reached, and on nothing before them.
 *
 * So the walk is by index now. `indexOf("\n")` finds each line, and the
 * separator rule, the `>From ` counter and the blank-line rule are all decided
 * against `text` in place: no line is cut out of the file, and nothing but a
 * handful of numbers is retained for a segment past the cap. `render` — the old
 * split / un-escape / join / trim, unchanged — runs at most `cap` times.
 *
 * MEASURED, both arms, node v24.9.0 on an Apple M1 Pro under load average ~2
 * (not an idle machine, so the absolutes are pessimistic and the ratio is the
 * stable part). Min of k, k=5 at 10 and 50 MB and k=3 above. The fixture is a
 * synthetic CRLF mbox at a real export's density — 661 bytes per message — so
 * the message counts line up with #810's own table:
 *
 *      MB   messages       splitMbox         parseMailFile        peak RSS
 *      10     15,129    20.4 ->   5.2 ms    19.9 ->   6.4 ms    399 ->   132 MB
 *      50     75,643   116.5 ->  27.8      113.8 ->  29.4       946 ->   253
 *     150    226,929   370.2 ->  83.4      438.5 ->  84.9     1,718 ->   634
 *     290    438,730   735.2 -> 158.5      800.8 -> 163.8     2,963 -> 1,157
 *     520    786,714 1,301.1 -> 289.2    1,531.7 -> 290.9     4,263 -> 1,595
 *
 * 520 MB IS NOT AN ARBITRARY TOP ROW. V8's maximum string length is 536,870,888
 * characters, so that is the largest file `File.text()` can hand this page at
 * all — see the cliff `ImportMail.onFile` brackets. The parse therefore cannot
 * cross a second on any input this page can accept any more; it used to cross
 * it at 290 MB. Peak RSS is sampled from outside the process every 4 ms, the
 * same instrument on both arms; the 1,595 MB the bounded scan peaks at is the
 * fixture string and its read buffer, and the split's own transient heap is no
 * longer measurable beside it.
 *
 * AND IT IS A WASH AT THE CAP, which is the size the ordinary import is. On a
 * 400-message export nothing is past the cap, everything is materialised either
 * way, and `parseMailFile` measures 1.87 -> 1.94 ms on 1,000-character bodies
 * and 7.40 -> 7.46 ms on 8,000-character ones. The whole win is in what is no
 * longer built, so it arrives with the file's size and not before.
 *
 * `total` IS STILL EXACT, which is the reason to walk to EOF rather than stop.
 * The count the page publishes is the post-re-join chunk count, and re-joining
 * needs only each block's HEAD (see `carriesAnEnvelope`, bounded to
 * MAX_ENVELOPE_SCAN_CHARS) plus whether the block held any text at all. Both
 * are O(1) per segment, so a bounded split reports the number an unbounded one
 * does and the sentence `ImportMail` prints did not have to change.
 *
 * THE CAP AND THE RE-JOIN MEET AT THE BOUNDARY. A block that carries no
 * envelope is appended to the chunk above it; when the retained set has just
 * reached `cap` that chunk is the last retained one, and it must still be
 * extended — or a capped split would return different TEXT for chunk `cap - 1`
 * than an uncapped one while `total` and `truncated` looked identical.
 */
export function splitMbox(text: string, cap: number = Infinity): MboxSplit {
  const chunks: MboxChunk[] = [];
  let total = 0;
  let unescaped = 0;
  let rejoined = 0;

  /**
   * The one place a message's text is built — character for character the
   * whole-file `render` this used to run on every segment, run on a range. The
   * trailing line terminator a range carries becomes an empty last element,
   * which `.trim()` removes, so a range and a segment render alike.
   */
  const render = (from: number, to: number) =>
    text
      .slice(from, to)
      .split(/\r?\n/)
      .map((l) => (l.startsWith(">From ") ? l.slice(1) : l))
      .join("\n")
      .trim();

  // The file walk. `offset` is MboxChunk.offset's coordinate — see there; it is
  // deliberately not the index this scan already has in hand.
  let offset = 0;
  let prevBlank = true; // start-of-file counts as "after a blank line"

  // The segment being accumulated, held as indices and counters only.
  let sepStart = -1; // its `From ` separator line, -1 for the head of the file
  let sepEnd = -1;
  let bodyStart = 0; // its first line, past the separator's terminator
  let segOffset = 0;
  let firstText = -1; // its first non-whitespace character: `render` starts here
  let sawEnvelope = false;
  let headOpen = true; // still inside the header block, still under the bound
  let headEnd = -1; // where the head stopped, for the fallback's sake
  let rawPos = 0; // where the NEXT rendered line starts, in `render`'s coordinates

  const startSegment = (from: number, to: number, body: number, at: number) => {
    sepStart = from;
    sepEnd = to;
    bodyStart = body;
    segOffset = at;
    firstText = -1;
    sawEnvelope = false;
    headOpen = true;
    headEnd = -1;
    rawPos = 0;
  };

  /**
   * Fold one line into the segment's head. Everything here is O(1) except the
   * whitespace search, which stops at the line's first non-space character.
   */
  const readLine = (lineStart: number, lineEnd: number, at: number) => {
    let start = lineStart;
    if (firstText === -1) {
      // Before the first non-whitespace character there is nothing: that is
      // exactly what `render`'s leading `.trim()` removes, so `raw` — and the
      // `^` the envelope test anchors on — begins here, not at the segment's
      // first line.
      if (at === -1) return;
      firstText = at;
      start = at;
    } else {
      if (!headOpen) return;
      // A rendered line of "" or "\r" is the blank line that ends the header
      // block: those are the only two shapes `raw.search(/\r?\n\r?\n/)` matches.
      if (
        lineEnd === lineStart ||
        (lineEnd - lineStart === 1 && text.charCodeAt(lineStart) === 0x0d)
      ) {
        headOpen = false;
        headEnd = lineStart;
        return;
      }
    }

    if (rawPos > MAX_ENVELOPE_SCAN_CHARS) {
      headOpen = false;
      headEnd = lineStart;
      return;
    }

    // `>From ` renders as `From `, which is neither `from:` nor `date:` — so an
    // escaped line is never an envelope line, and the character the un-escape
    // removes only has to be paid into `rawPos`.
    const escaped = text.startsWith(">From ", lineStart);
    if (!escaped && rawPos + ENVELOPE_FIELD_CHARS <= MAX_ENVELOPE_SCAN_CHARS) {
      ENVELOPE_FIELD.lastIndex = start;
      if (ENVELOPE_FIELD.test(text)) {
        sawEnvelope = true;
        headOpen = false;
        return;
      }
    }
    rawPos += lineEnd - start - (escaped ? 1 : 0) + 1;
  };

  const closeSegment = (endsAt: number) => {
    // Blank runs between messages, and the empty head of every file that opens
    // on a separator. Never counted: they are not a decision.
    if (firstText === -1) return;

    if (total > 0) {
      // The pre-filter only ever says yes where the real predicate would, so
      // the head is built exactly when the cheap answer came back empty — which
      // in a well-formed export is never. `headEnd` is where the walk stopped
      // reading the header block, so what gets built is MAX_ENVELOPE_SCAN_CHARS
      // plus a line; `-1` means the block ended first and is smaller still. The
      // one input that builds more is a block with no line ending in it at all,
      // and the split it replaces built that block too.
      //
      // AND IT IS THE ONE PLACE `render` STARTS MID-LINE, which is safe only
      // because of an argument that is not visible from here. If `firstText`
      // sat past its line's start on a line beginning `">From "`, this slice's
      // first element WOULD match `startsWith(">From ")` and be un-escaped,
      // while the real `raw` — rendered from `bodyStart`, where the full line
      // `"  >From x"` does not match — would not. `firstText` can only sit past
      // a line's start when that line opens with whitespace, and the only
      // segment that can begin on such a line is the head of the file: every
      // other one begins on a line `HEADER_LINE` accepted, which starts with a
      // letter. The head of the file has no separator and closes with
      // `total === 0`, so it never reaches this branch. RELAXING THE SEPARATOR
      // RULE WOULD MAKE THAT LIVE — render from `bodyStart` here if it changes.
      const envelope =
        sawEnvelope || carriesAnEnvelope(render(firstText, headEnd === -1 ? endsAt : headEnd));
      if (!envelope) {
        rejoined += 1;
        // The chunk this belongs to is index `total - 1`, which is in `chunks`
        // only while that index is under the cap. Past the cap the re-join is
        // counted and nothing is built — that is the point — but AT the cap the
        // previous chunk is retained and must still be extended.
        if (total <= cap) {
          const previous = chunks[chunks.length - 1];
          const separator = sepStart === -1 ? "" : text.slice(sepStart, sepEnd);
          previous.raw = `${previous.raw}\n\n${separator}\n${render(bodyStart, endsAt)}`;
        }
        return;
      }
    }

    total += 1;
    if (total <= cap) chunks.push({ raw: render(bodyStart, endsAt), offset: segOffset });
  };

  for (let lineStart = 0; ; ) {
    const nl = text.indexOf("\n", lineStart);
    const last = nl === -1;
    // The line as `split(/\r?\n/)` would have produced it: one `\r` before the
    // `\n` belongs to the terminator, any further one belongs to the line.
    const lineEnd = last
      ? text.length
      : nl > lineStart && text.charCodeAt(nl - 1) === 0x0d
        ? nl - 1
        : nl;

    const startsAt = offset;
    offset += lineEnd - lineStart + 1;

    // `startsWith` cannot reach past the line: the fifth character it needs is
    // a space, and a shorter line puts `\r` or `\n` there instead.
    if (prevBlank && text.startsWith("From ", lineStart)) {
      if (!last) {
        HEADER_LINE.lastIndex = nl + 1;
        if (HEADER_LINE.test(text)) {
          closeSegment(lineStart);
          startSegment(lineStart, lineEnd, nl + 1, startsAt);
          prevBlank = false;
          lineStart = nl + 1;
          continue; // the "From " separator line itself is not part of the message
        }
      }
      // Not a separator. Keep it as the body text it is, and remember that
      // this file made us decide.
      unescaped += 1;
    }

    const at = firstNonSpace(text, lineStart, lineEnd);
    readLine(lineStart, lineEnd, at);
    prevBlank = at === -1;

    if (last) break;
    lineStart = nl + 1;
  }
  closeSegment(text.length);

  return { chunks, total, malformed: malformedNote(unescaped, rejoined) };
}

// ---------------------------------------------------------------------------
// JSON parsing
// ---------------------------------------------------------------------------

interface LooseJsonMessage {
  subject?: unknown;
  from?: unknown;
  sender?: unknown;
  sender_email?: unknown;
  senderEmail?: unknown;
  senderName?: unknown;
  body?: unknown;
  text?: unknown;
  snippet?: unknown;
  date?: unknown;
  receivedAt?: unknown;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

/**
 * ONE ENTRY MUST NOT DISCARD THE FILE — the same shape as the prototype bug
 * fixed in #404, arriving through the other public input.
 *
 * The parameter is `unknown` because a JSON array holds whatever the file said,
 * and the declared element type is a claim about the happy path rather than
 * something the wire is obliged to honour. `[null, …]` threw:
 *
 *   TypeError: Cannot read properties of null (reading 'subject')
 *
 * and `ImportMail.ingest` wraps the whole parse in one try/catch, so a single
 * `null` in a 400-record batch produced "Couldn't parse that file" about all
 * 400 of them.
 *
 * The root cause is fixed rather than the symptom caught: a non-object entry
 * returns null, which the caller already counts as `unreadable` and the UI
 * already reports. That is deliberately NOT a wider class than it was —
 * numbers, booleans and strings never threw (property access on them yields
 * `undefined`) and already landed in `unreadable`. `null` and `undefined` are
 * the two shapes that threw, and they now behave like the rest.
 */
function parseJsonMessage(entry: unknown, salt: string): ParsedMessage | null {
  if (typeof entry !== "object" || entry === null) return null;
  const item = entry as LooseJsonMessage;

  const subject = str(item.subject).trim().slice(0, MAX_SUBJECT_CHARS);
  const body = str(item.body ?? item.text ?? item.snippet);
  const fromField = str(item.from ?? item.sender ?? item.sender_email ?? item.senderEmail);
  if (!subject && !fromField && !body.trim()) return null;

  const parsed = fromField ? parseFrom(fromField) : { name: null, email: "" };
  const name = str(item.senderName).trim() || parsed.name;
  const email = parsed.email || str(item.sender_email ?? item.senderEmail).toLowerCase();
  const collapsed = collapse(body);
  const date = str(item.date ?? item.receivedAt);

  return {
    // Same rule as the RFC-822 path (see `contentId`), over the fields a JSON
    // record identifies itself by. There is no `Message-ID` here to prefer:
    // this format is a hand-assembled batch, and honouring a caller-supplied
    // id would put identity back in the file's gift.
    //
    // `JSON.stringify` rather than a join, so one record cannot be turned
    // into another by moving a space across a field boundary, and each field
    // is cut BEFORE it is quoted so a megabyte body is never copied to make
    // a key.
    id: contentId(
      undefined,
      JSON.stringify([
        subject.slice(0, MAX_FROM_CHARS),
        fromField.slice(0, MAX_FROM_CHARS),
        date.slice(0, MAX_FROM_CHARS),
        body.slice(0, MAX_ID_HASH_CHARS),
      ]),
      salt,
    ),
    subject: subject || "(no subject)",
    senderName: name || null,
    senderEmail: email || "(unknown sender)",
    body: body.slice(0, MAX_BODY_CHARS),
    snippet: collapsed.slice(0, SNIPPET_CHARS),
    receivedAt: date || null,
  };
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/**
 * One thing to parse, with where it was found. The salt is NOT the id — see
 * `contentId`; it exists only so two byte-identical messages in one file can
 * be told apart.
 */
interface Candidate {
  value: unknown;
  salt: string;
}

/**
 * Make an id unique within one result, keeping the first claim on it.
 *
 * THE KEYS REACT IS GIVEN HAVE TO BE DISTINCT, and a content-derived id can
 * legitimately repeat: a Takeout export contains the same message once per
 * label it carries, with the same `Message-ID:` each time. Duplicate keys put
 * React back in the state #426 is about — it matches the first of them and the
 * rows swap their disclosure state around — so the repeat is suffixed rather
 * than left to collide, and rows for the same message stay separate rows.
 */
function distinct(id: string, taken: Set<string>): string {
  let unique = id;
  for (let n = 2; taken.has(unique); n++) unique = `${id}~${n}`;
  taken.add(unique);
  return unique;
}

export function parseMailFile(
  filename: string,
  text: string,
  cap: number = DEFAULT_MESSAGE_CAP,
): ParseResult {
  const format = detectFormat(filename, text);

  let raws: Candidate[] = [];
  let malformed: string | null = null;
  /**
   * How many messages the file holds, when that is not `raws.length`.
   *
   * It is `raws.length` on every path but one. The mbox split stops
   * MATERIALISING at the cap (#810) and counts to EOF separately, so on that
   * path `raws` is the first `cap` messages and this is all of them.
   */
  let found: number | null = null;
  if (format === "json") {
    const data = JSON.parse(text) as unknown;
    const arr = Array.isArray(data)
      ? data
      : Array.isArray((data as { messages?: unknown }).messages)
        ? (data as { messages: unknown[] }).messages
        : [];
    raws = arr.map((value, i) => ({ value, salt: String(i) }));
  } else if (format === "mbox") {
    const split = splitMbox(text, cap);
    malformed = split.malformed;
    found = split.total;
    raws = split.chunks.map((chunk) => ({ value: chunk.raw, salt: String(chunk.offset) }));
  } else {
    // The one format that is defined as a single message, and the one that had
    // no bound. See MAX_SINGLE_MESSAGE_CHARS — this refuses rather than
    // truncating, because a truncated message classified as though it were the
    // whole one is a verdict about mail we did not read.
    const single = text.trim();
    if (single.length > MAX_SINGLE_MESSAGE_CHARS) {
      throw new MailTooLargeError(
        `That file is a single ${Math.round(single.length / 1_000_000)}MB message, which is larger ` +
          "than any message a mail provider will carry, so it cannot be classified as one. " +
          "If it is really a mailbox export, save it with a .mbox extension and drop it again.",
      );
    }
    raws = [{ value: single, salt: "0" }];
  }

  const totalFound = found ?? raws.length;
  // A no-op on the mbox path, where the split already stopped at `cap`. It is
  // what applies the cap on the other two, which materialise their whole file.
  const capped = raws.slice(0, cap);

  const messages: ParsedMessage[] = [];
  const taken = new Set<string>();
  for (const { value, salt } of capped) {
    const msg =
      format === "json" ? parseJsonMessage(value, salt) : parseRfc822(value as string, salt);
    if (!msg) continue;
    msg.id = distinct(msg.id, taken);
    messages.push(msg);
  }

  return {
    format,
    messages,
    totalFound,
    truncated: totalFound > capped.length,
    unreadable: capped.length - messages.length,
    malformed,
  };
}
