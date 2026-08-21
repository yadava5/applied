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
  /** Messages detected in the file before the cap was applied. */
  totalFound: number;
  /** True when `totalFound` exceeded the cap and `messages` was trimmed. */
  truncated: boolean;
}

/** Keep the tab responsive: a Takeout mbox can hold tens of thousands of mails. */
export const DEFAULT_MESSAGE_CAP = 400;

/** Upper bound on decoded body length handed to the classifier. */
const MAX_BODY_CHARS = 8000;
const SNIPPET_CHARS = 180;

// ---------------------------------------------------------------------------
// Format detection
// ---------------------------------------------------------------------------

export function detectFormat(filename: string, text: string): MailFormat {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".mbox")) return "mbox";
  if (lower.endsWith(".eml")) return "eml";

  // Content sniffing for drag-and-drop or oddly-named files.
  const head = text.slice(0, 4000).trimStart();
  if (head.startsWith("[") || head.startsWith("{")) return "json";
  // An mbox begins with a "From " separator line; a lone .eml usually starts
  // straight into headers.
  if (/^From .+\n/.test(head)) return "mbox";
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

function base64ToUtf8(b64: string): string {
  try {
    const clean = b64.replace(/\s+/g, "");
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

/** Parse a `From:` value into a display name + bare email address. */
export function parseFrom(value: string): { name: string | null; email: string } {
  const decoded = decodeEncodedWords(value).trim();
  const angle = decoded.match(/^(.*?)<([^>]+)>\s*$/);
  if (angle) {
    let name = angle[1].trim().replace(/^"(.*)"$/, "$1").trim();
    if (!name) name = "";
    return { name: name || null, email: angle[2].trim().toLowerCase() };
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
  let text = body;
  if (enc === "base64") text = base64ToUtf8(body);
  else if (enc === "quoted-printable") text = decodeQuotedPrintable(body);
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

/** Parse a single raw RFC-822 message into the fields the classifier needs. */
export function parseRfc822(raw: string, id: string): ParsedMessage | null {
  const { headerBlock, body } = splitHeadersAndBody(raw);
  const headers = parseHeaders(headerBlock);

  const subjectRaw = headers.get("subject") ?? "";
  const fromRaw = headers.get("from") ?? "";
  if (!subjectRaw && !fromRaw && !body.trim()) return null;

  const subject = decodeEncodedWords(subjectRaw).trim();
  const { name, email } = parseFrom(fromRaw);

  const fullText = extractText(headers, body).slice(0, MAX_BODY_CHARS);
  const collapsed = collapse(fullText);

  return {
    id,
    subject: subject || "(no subject)",
    senderName: name,
    senderEmail: email || "(unknown sender)",
    body: fullText,
    snippet: collapsed.slice(0, SNIPPET_CHARS),
    receivedAt: headers.get("date") ?? null,
  };
}

/**
 * Split an mbox into raw messages. A separator is a line beginning with
 * `From ` that either starts the file or follows a blank line (the standard
 * mbox rule) — this avoids false splits on body lines that merely start with
 * "From ". Body `>From ` escapes (mboxrd) are unescaped.
 */
export function splitMbox(text: string): string[] {
  const lines = text.split(/\r?\n/);
  const messages: string[] = [];
  let current: string[] = [];
  let prevBlank = true; // start-of-file counts as "after a blank line"

  const push = () => {
    if (current.length) {
      const raw = current
        .map((l) => (l.startsWith(">From ") ? l.slice(1) : l))
        .join("\n")
        .trim();
      if (raw) messages.push(raw);
    }
    current = [];
  };

  for (const line of lines) {
    if (prevBlank && /^From /.test(line)) {
      push();
      prevBlank = false;
      continue; // drop the "From " separator line itself
    }
    current.push(line);
    prevBlank = line.trim() === "";
  }
  push();
  return messages;
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

function parseJsonMessage(item: LooseJsonMessage, id: string): ParsedMessage | null {
  const subject = str(item.subject).trim();
  const body = str(item.body ?? item.text ?? item.snippet);
  const fromField = str(item.from ?? item.sender ?? item.sender_email ?? item.senderEmail);
  if (!subject && !fromField && !body.trim()) return null;

  const parsed = fromField ? parseFrom(fromField) : { name: null, email: "" };
  const name = str(item.senderName).trim() || parsed.name;
  const email = parsed.email || str(item.sender_email ?? item.senderEmail).toLowerCase();
  const collapsed = collapse(body);

  return {
    id,
    subject: subject || "(no subject)",
    senderName: name || null,
    senderEmail: email || "(unknown sender)",
    body: body.slice(0, MAX_BODY_CHARS),
    snippet: collapsed.slice(0, SNIPPET_CHARS),
    receivedAt: str(item.date ?? item.receivedAt) || null,
  };
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export function parseMailFile(
  filename: string,
  text: string,
  cap: number = DEFAULT_MESSAGE_CAP,
): ParseResult {
  const format = detectFormat(filename, text);

  let raws: LooseJsonMessage[] | string[] = [];
  if (format === "json") {
    const data = JSON.parse(text) as unknown;
    const arr = Array.isArray(data)
      ? data
      : Array.isArray((data as { messages?: unknown }).messages)
        ? (data as { messages: unknown[] }).messages
        : [];
    raws = arr as LooseJsonMessage[];
  } else if (format === "mbox") {
    raws = splitMbox(text);
  } else {
    raws = [text.trim()];
  }

  const totalFound = raws.length;
  const capped = raws.slice(0, cap);

  const messages: ParsedMessage[] = [];
  capped.forEach((item, i) => {
    const id = `m${i}`;
    const msg =
      format === "json"
        ? parseJsonMessage(item as LooseJsonMessage, id)
        : parseRfc822(item as string, id);
    if (msg) messages.push(msg);
  });

  return { format, messages, totalFound, truncated: totalFound > capped.length };
}
