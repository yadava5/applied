"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { Mail } from "lucide-react";

import { QuietEnvelope } from "@/components/boot/QuietEnvelope";
import { MailText } from "@/components/mail/MailText";
import { GATE } from "@/lib/classification/gate";
import { classifyWithRules } from "@/lib/demo/rulesLayer";
import {
  DEFAULT_MESSAGE_CAP,
  MailTooLargeError,
  parseMailFile,
  type MailFormat,
  type ParsedMessage,
} from "@/lib/import/parseMail";

/**
 * "Import your mail" — classify your own mail with NO Google connection and
 * NO sign-in. The file is read, parsed, and classified entirely in this tab
 * with `parseMail.ts` + the on-device rules layer (`rulesLayer.ts`) — the same
 * layer 1 the live sample inbox runs. Nothing is uploaded; there is no server
 * call and no OAuth, which is exactly why it reinforces the privacy story.
 *
 * Honesty: only the deterministic layer-1 rules run here. The full three-layer
 * model (e5 embeddings + the SetFit head) needs the 23 MB ONNX weights, which
 * the strict CSP keeps out of the tab — that runs in `/demo/inbox` and the
 * Hugging Face Space. We label the layer-1 disposition on every row.
 *
 * Copy: the on-device claim is ONE line, directly under the drop zone it
 * covers — the in-context disclosure at the exact moment a user hands over a
 * file — linking to the privacy policy's "On-device import" section, which
 * owns the mechanism detail (what runs on this page, what never does; #201).
 * The page used to restate the claim four times before the first button; the
 * pile-up read as protesting too much and pushed the control below the fold.
 * #198 finished the thought: the drop zone leads, sized like the page's one
 * action, and the note reads as its caveat. The per-row traces keep the
 * technical register. `import.spec.ts` pins "On-device only" and "the mail
 * never leaves your device" as visible on load, so the surviving sentence is
 * load-bearing — reword it only together with the spec.
 */

/** Layer-1 accept bar from the shipped pipeline: rules answer at ≥ 0.90. */
const RULES_ACCEPT = 0.9;

const CATEGORY_DOT: Record<string, string> = {
  offer: "var(--green)",
  interview: "var(--viz-rules)",
  assessment: "var(--viz-embeddings)",
  applied: "var(--text-muted)",
  pending_application: "var(--viz-embeddings)",
  follow_up: "var(--viz-setfit)",
  rejection: "var(--red)",
  other: "var(--text-dim)",
};

const FORMAT_LABEL: Record<MailFormat, string> = {
  mbox: "Google Takeout MBOX",
  eml: "single .eml message",
  json: "JSON batch",
};

interface Classified extends ParsedMessage {
  category: string;
  confidence: number;
  answeredByRules: boolean;
  clearsGate: boolean;
  topScores: [string, number][];
}

interface ImportState {
  fileName: string;
  format: MailFormat;
  totalFound: number;
  truncated: boolean;
  /** Read but unparseable. See ParseResult.unreadable in lib/import/parseMail. */
  unreadable: number;
  /** Non-null when the file's own structure was ambiguous. See ParseResult.malformed. */
  malformed: string | null;
  items: Classified[];
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

/** Bytes as a person reads them, for the file-too-large message. */
function formatBytes(bytes: number) {
  const gb = bytes / 1_000_000_000;
  if (gb >= 1) return `${gb.toFixed(1)}GB`;
  return `${Math.round(bytes / 1_000_000)}MB`;
}

function pretty(category: string) {
  return category.replace(/_/g, " ");
}

function classifyOne(m: ParsedMessage): Classified {
  const v = classifyWithRules(m.subject, m.body, m.senderEmail);
  const topScores = Object.entries(v.scores)
    .filter(([, s]) => s > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  return {
    ...m,
    category: v.category,
    confidence: v.confidence,
    answeredByRules: v.confidence >= RULES_ACCEPT && v.category !== "other",
    clearsGate: v.confidence >= GATE && v.category !== "other",
    topScores,
  };
}

/**
 * HOW MANY MESSAGES ONE BATCH CLASSIFIES BEFORE THE PASS HANDS THE MAIN THREAD
 * BACK — and the measurement the number comes from.
 *
 * This pass used to be a single synchronous `messages.map(classifyOne)`. The
 * tab cannot paint during that, so any indicator drawn over it would have been
 * a still picture of work in progress: #390 was filed for the indicator and
 * stayed open because the loop had to yield before one could be honest.
 *
 * Measured through the shipped `classifyWithRules` on this machine (Apple
 * Silicon, node 24.9.0, min of 21 runs) on synthetic mail across six
 * categories — 84% of it answered by a rule, so this is the matching path and
 * not the cheap miss path a repeated-character fixture would have measured:
 *
 *                        1,000-char bodies    4,000     8,000 = MAX_BODY_CHARS
 *   per message                  0.157 ms     0.468      0.880 ms
 *   whole 400-message pass        62.6 ms     187.1      352.1 ms
 *   chunk 12                       1.86 ms      5.58      10.42 ms  · 34 batches
 *   chunk 16                       2.47 ms      7.41      13.91 ms  · 25 batches
 *   chunk 20                       3.08 ms      9.21      17.36 ms  · 20 batches
 *
 * 16 is the largest chunk whose batch still fits inside a 60 Hz frame
 * (16.7 ms) on the WORST input this page can produce — `MAX_BODY_CHARS`
 * truncates a body before the classifier sees it, so 8,000 characters is a
 * ceiling and not a guess, and `DEFAULT_MESSAGE_CAP` bounds the count at 400.
 * Twenty drops a frame per batch on that input; twelve buys nothing, because a
 * yield costs a task whether it carried 12 messages or 16, and it turns the
 * field below into 34 marks nobody can count.
 */
const CLASSIFY_BATCH = 16;

/**
 * How long the visitor waits before an indicator is worth drawing at all.
 *
 * The threshold itself is not a measurement — it is the ~0.1 s bound below
 * which an interface reads as instantaneous (Card & Miller; Nielsen, "Response
 * Times"). What IS measured is which passes cross it, counted in Chrome at the
 * 400-message cap by how many batches the field was actually drawn for:
 *
 *   1,000-char bodies    92.4 ms end to end     0 of 25 batches drawn
 *   4,000-char bodies   300.2 ms               17 of 25
 *   8,000-char bodies   557.7 ms               23 of 25
 *
 * So the small file never draws anything — a field flashing on for four frames
 * would be worse than the whisper it replaces — and the file that made someone
 * wait draws almost the whole pass.
 *
 * THE CLOCK STARTS WHEN THE FILE IS HANDED OVER, not when the classify pass
 * does, because that is when the visitor's wait started: `file.text()` and
 * `parseMailFile` run first and neither is instant — the mbox split alone is
 * 538 ms on a 150 MB export, which is #810's subject and not this pass's. So
 * on any file big enough to have made somebody wait, the field is up from the
 * first batch.
 *
 * It gates the REVEAL and nothing else. What the field then draws is the real
 * count; no threshold can make it move.
 */
const CLASSIFY_REVEAL_MS = 100;

/**
 * Hand the main thread back so React can commit the batch that just finished
 * and the browser can paint it.
 *
 * A MACROTASK, AND DELIBERATELY NOT `setTimeout`. A microtask (`await
 * Promise.resolve()`) runs before the next rendering opportunity, so the whole
 * file would classify without a single paint and the field would jump from
 * empty to full — the frozen indicator again, one await later.
 * `requestAnimationFrame` fails the other way: a hidden tab pauses it
 * outright, so somebody who switches away mid-import comes back to a pass that
 * never finished. That leaves `setTimeout(0)`, which is a real task but pays
 * the nesting clamp from the fifth nested timer onward, and a `MessageChannel`
 * message, which is a task with neither clamp nor visibility throttle and is
 * what React's own scheduler reaches for.
 *
 * Measured in Chrome on the 400-message worst case, both arms through this
 * component, timing the whole wait from the file being handed over to the rows
 * rendering — 24 yields per pass:
 *
 *   MessageChannel   538.3 / 536.9 ms   yields 54.9–61.7 ms   2.29–2.57 ms each
 *   setTimeout(0)    583.2 / 587.1 ms   yields 103.1–105.5 ms 4.30–4.40 ms each
 *
 * Both per-yield figures include the paint the gap exists to buy; the ~2 ms
 * between them is the clamp, and it costs about 48 ms of the visitor's wait
 * per import. An indicator whose machinery adds 9% to the duration it reports
 * on is measuring itself, so the channel wins.
 */
function nextTask(): Promise<void> {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => {
      channel.port1.close();
      resolve();
    };
    channel.port2.postMessage(null);
  });
}

/**
 * Classify every message, a batch at a time, reporting the count that is
 * actually done after each one.
 *
 * `onBatch` fires once per batch that RETURNED, with the real running total —
 * so a pass that stalls stops the display with it, and a batch that throws
 * never reports. That is the whole honesty argument for the field this drives:
 * there is no clock and no estimate anywhere in it.
 *
 * `isCurrent` is what a second file interrupting the first looks like from in
 * here. Nothing else can supersede a pass, and a pass that has been superseded
 * must stop rather than keep spending the tab's main thread on results no one
 * will see — it returns null, which is the caller's signal to write nothing.
 */
async function classifyPass(
  messages: ParsedMessage[],
  { onBatch, isCurrent }: { onBatch: (classified: number) => void; isCurrent: () => boolean },
): Promise<Classified[] | null> {
  const items: Classified[] = [];
  for (let start = 0; start < messages.length; start += CLASSIFY_BATCH) {
    const end = Math.min(start + CLASSIFY_BATCH, messages.length);
    for (let i = start; i < end; i += 1) items.push(classifyOne(messages[i]));
    if (!isCurrent()) return null;
    onBatch(items.length);
    // No yield after the last batch: the caller renders the rows in the same
    // task, so the paint this would buy is one the results replace.
    if (end < messages.length) await nextTask();
  }
  return items;
}

/**
 * One classified message.
 *
 * EXPORTED, AND RENAMED FROM `Row`, so the suite can render it (#424). This is
 * the row `/import` draws, and `/import` is public and unauthenticated, so
 * every string on it came from a stranger. A bidi override or a zero-width
 * character in a subject is invisible to source inspection by construction —
 * the only honest check is to render the hostile bytes and read what comes
 * out — and `ImportMail` itself cannot be rendered without a real file drop.
 */
export function ImportRow({ item }: { item: Classified }) {
  const [open, setOpen] = useState(false);
  const dot = CATEGORY_DOT[item.category] ?? "var(--text-dim)";
  const meterPct = Math.round(item.confidence * 100);

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid="import-row"
        className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
      >
        <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <p className="truncate text-sm font-medium text-strong">
            <MailText value={item.subject} />
          </p>
          <p className="truncate text-xs text-dim">
            {item.senderName ? (
              <>
                <MailText value={item.senderName} />
                {" · "}
              </>
            ) : null}
            <MailText value={item.senderEmail} />
          </p>
        </div>

        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: dot }} aria-hidden />
          {pretty(item.category)}
        </span>

        {item.clearsGate ? (
          <span className="hidden w-16 text-[10px] font-semibold uppercase tracking-wide text-dim sm:inline">
            auto-filed
          </span>
        ) : (
          <span className="rounded-full border border-review/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-review">
            review
          </span>
        )}

        <span
          className="tabular w-12 shrink-0 text-right font-mono text-xs"
          style={{ color: item.clearsGate ? "var(--green)" : "var(--amber)" }}
        >
          {pct(item.confidence)}
        </span>
      </button>

      {open && (
        <div className="border-t border-line-soft bg-surface-2/50 px-4 py-4">
          {/* layer-1 disposition */}
          <p className="flex items-start gap-2 font-mono text-[11px] text-muted">
            <span
              className="mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full"
              style={{ background: "var(--viz-rules)" }}
              aria-hidden
            />
            <span>
              layer 1 · rules —{" "}
              {item.answeredByRules
                ? `answered “${pretty(item.category)}” at ${pct(item.confidence)} (≥ 0.90 accept bar)`
                : `top guess “${pretty(item.category)}” at ${pct(item.confidence)}; below the 0.90 accept bar, so the full model (e5 → SetFit) would decide`}
            </span>
          </p>

          {/* confidence meter vs the 0.85 gate */}
          <div className="mt-4">
            <div className="relative h-2 rounded-full bg-surface">
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{
                  width: `${meterPct}%`,
                  background: item.clearsGate ? "var(--green)" : "var(--amber)",
                }}
              />
              <div
                className="absolute inset-y-[-4px] w-px bg-line-strong"
                style={{ left: `${GATE * 100}%` }}
              />
            </div>
            <div className="mt-1.5 flex justify-between font-mono text-[10px] text-dim">
              <span>0%</span>
              <span style={{ marginLeft: `${GATE * 100 - 10}%` }}>gate {GATE}</span>
              <span>100%</span>
            </div>
          </div>

          <p className="mt-3 text-xs leading-relaxed text-dim">
            {item.clearsGate
              ? `Clears the 0.85 gate — Applied would file this as “${pretty(item.category)}”.`
              : "Below the 0.85 gate — nothing is auto-filed; the message waits for a human (or the full model)."}
          </p>

          {item.topScores.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {item.topScores.map(([cat, score]) => (
                <span
                  key={cat}
                  className="rounded border border-line-soft px-2 py-0.5 font-mono text-[10px] text-dim"
                >
                  {pretty(cat)} +{score}
                </span>
              ))}
            </div>
          )}

          {item.snippet && (
            <p className="mt-3 border-t border-line-soft pt-3 text-[12px] leading-relaxed text-muted">
              <MailText value={item.snippet} />
              {item.body.length > item.snippet.length ? "…" : ""}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * The classify pass, drawn from the count the browser genuinely has.
 *
 * ONE ENVELOPE IS ONE BATCH, which is what makes this an indicator rather than
 * a texture: the field holds `ceil(total / CLASSIFY_BATCH)` envelopes, and an
 * envelope is lit when its batch has RETURNED. Stall the pass and the field
 * stalls; throw in a batch and the envelopes past it never light. There is no
 * percentage and no elapsed clock in here — the rule `lib/gmail/sync-plan.ts`
 * states for the server sync, where a percentage over one round trip would be
 * "a timer wearing a costume". What is different here is that the pass runs in
 * this tab, so the count is a fact rather than a costume, and a fact may be
 * shown.
 *
 * IT IS THE SKELETON'S OWN GLYPH. `app/(app)/import/loading.tsx` puts a
 * `QuietEnvelope` at the centre of this exact drop zone while the route is
 * pending; this is that envelope, multiplied by the work, at the moment the
 * work is real — and standing still between batches, because unlike the
 * skeleton it has something true to say. `.import-classify` in globals.css
 * turns the shared wave off and records why.
 *
 * Reduced motion therefore needs no branch at all: there is no motion in the
 * field except envelopes lighting, which is the progress itself. WCAG 2.2.2
 * exempts a progress indicator in any case, and this one ends when the pass
 * does.
 *
 * `role="progressbar"` rather than a live region on the count line: a status
 * region would announce all 25 batches inside a third of a second, and a
 * progress bar is the role assistive technology already paces for the reader.
 * `aria-label` deliberately does not start with "Loading" — that prefix is half
 * of BootOverlay's PENDING_SELECTOR and would hold the boot loop on screen.
 */
function ClassifyField({ classified, total }: { classified: number; total: number }) {
  const batches = Math.ceil(total / CLASSIFY_BATCH);
  const done = Math.ceil(classified / CLASSIFY_BATCH);
  return (
    <div
      // `min-h-8` is the lucide `Mail` this stands in for: at every width that
      // fits the field on one line the drop zone's height is unchanged, so the
      // swap costs no reflow. Below that it wraps and the zone grows a row,
      // which is the honest trade — the alternative is clipping the count.
      className="import-classify mx-auto flex min-h-8 flex-wrap items-center justify-center gap-1.5"
      role="progressbar"
      aria-label="Classifying your mail"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={classified}
    >
      {Array.from({ length: batches }, (_, i) => (
        <QuietEnvelope key={i} index={i} lit={i < done} className="h-[14px] w-5" />
      ))}
    </div>
  );
}

export function ImportMail() {
  const [state, setState] = useState<ImportState | null>(null);
  const [error, setError] = useState<string | null>(null);
  /**
   * The file the tab is working on, or null when it is at rest.
   *
   * This was a `busy` boolean, and the name is the whole reason it changed: the
   * zone has to say WHICH file, not merely that something is happening. Two
   * exports of the same mailbox differ by their name and by nothing else on
   * screen, and dropping the second over the first is a supported move.
   */
  const [pendingFile, setPendingFile] = useState<string | null>(null);
  /**
   * The classify pass's real position, or null when there is nothing true to
   * draw. Two numbers and no third: `classified` is what has come back from
   * `classifyPass`, `total` is what `parseMailFile` handed it. Anything else
   * here — an elapsed time, a rate, a percentage — would be a number the page
   * invented rather than counted.
   *
   * `total` IS `messages.length`, not `totalFound` and not the cap, and it can
   * therefore read "192 of 393" on a file that lost seven entries to parsing.
   * That is deliberate and it is the same rule the summary line below already
   * follows: this counter's denominator is the work there is to do, and an
   * entry that produced no message is not work this pass will ever reach.
   */
  const [progress, setProgress] = useState<{ classified: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  /**
   * WHICH FILE THE TAB IS CURRENTLY IMPORTING, as a token every write is
   * checked against.
   *
   * `ingest` used to be synchronous, so a second file could not begin until the
   * first had finished and no guard was needed. It yields now, and both the
   * picker and the drop target can start a pass over a running one — at which
   * point the first pass's `setProgress` advances a count belonging to a file
   * nobody is looking at any more, against the second file's total. An
   * indicator that can be made to show one file's progress for another is
   * exactly the failure this work exists to prevent, so the token is taken
   * before the first await and every write past one is dropped.
   */
  const passRef = useRef(0);

  const ingest = useCallback(
    async (fileName: string, text: string, pass: number, startedAt: number) => {
      const isCurrent = () => passRef.current === pass;
      setError(null);
      try {
        const result = parseMailFile(fileName, text);
        if (!isCurrent()) return;
        if (result.messages.length === 0) {
          setState(null);
          setError(
            "No messages found in that file. Expected a Google Takeout .mbox, a single .eml, or a JSON array of { subject, from, body }.",
          );
          return;
        }
        const items = await classifyPass(result.messages, {
          onBatch: (classified) => {
            // The gate is on the visitor's wait, not on the count: past it,
            // every batch draws. Before it, the pass is short enough that
            // drawing anything would be a flash. See CLASSIFY_REVEAL_MS.
            if (performance.now() - startedAt < CLASSIFY_REVEAL_MS) return;
            setProgress({ classified, total: result.messages.length });
          },
          isCurrent,
        });
        if (items === null) return;
        setState({
          fileName,
          format: result.format,
          totalFound: result.totalFound,
          truncated: result.truncated,
          unreadable: result.unreadable,
          malformed: result.malformed,
          items,
        });
      } catch (err) {
        if (!isCurrent()) return;
        setState(null);
        /**
         * A REFUSAL AND A FAILURE NEED DIFFERENT WORDS. "Couldn't parse that
         * file" is a guess about the format, and telling somebody their valid
         * message is malformed sends them off to re-export it. `MailTooLargeError`
         * is a fact about the size, and it carries its own sentence — see
         * MAX_SINGLE_MESSAGE_CHARS in lib/import/parseMail.
         */
        setError(
          err instanceof MailTooLargeError
            ? err.message
            : "Couldn't parse that file. Make sure it's a valid .mbox, .eml, or JSON export.",
        );
      }
    },
    [],
  );

  const onFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      const pass = (passRef.current += 1);
      const startedAt = performance.now();
      setPendingFile(file.name);
      setProgress(null);
      try {
        /**
         * DELIBERATELY NO `file.size` GATE BEFORE THIS READ, and the reason is
         * the comment below it: a 520MB Takeout mbox holding 786,800 messages
         * IS a supported input on this page, and any byte threshold big enough
         * to keep working would be too big to bound anything.
         *
         * The bound that issue #406 asks for is on the single-message `.eml`
         * path, and it can only be applied once the format is known —
         * `detectFormat` reclassifies an mbox saved as `.eml` by its CONTENT,
         * so a pre-read check keyed on the extension would refuse exactly the
         * renamed export that sniff exists to rescue. It therefore lives in
         * `parseMailFile` (MAX_SINGLE_MESSAGE_CHARS) and surfaces through the
         * `MailTooLargeError` branch of `ingest`.
         */
        const text = await file.text();
        if (passRef.current !== pass) return;

        /**
         * A FILE THE BROWSER COULD NOT HOLD, told apart from an empty one.
         *
         * Above roughly 512MB, V8's maximum string length, Chromium's
         * `File.text()` RESOLVES WITH AN EMPTY STRING rather than rejecting.
         * So the try/catch below never fires, the empty string parses to zero
         * messages, and the page told the visitor:
         *
         *   "No messages found in that file. Expected a Google Takeout
         *    .mbox, a single .eml, or a JSON array..."
         *
         * about a valid 1.1GB Takeout mbox holding 1,664,400 messages, on a
         * page whose own instructions tell them to produce exactly that file.
         * Measured by wrapping `File.prototype.text` before the bundle ran:
         * `file.size` was the full 1,100,047,731 bytes and `text().length` was
         * 0. The cliff sits between 520,017,757 bytes (works, 786,800 messages
         * found) and 540,109,953 (fails).
         *
         * The condition is `size > 0 && text === ""`, which is the observed
         * failure exactly. It is deliberately not a byte threshold: the limit
         * is engine-specific, so a hard-coded number would be wrong in Safari
         * and would rot when V8 changes. A genuinely empty file has size 0 and
         * still gets the ordinary message.
         */
        if (file.size > 0 && text.length === 0) {
          setState(null);
          setError(
            `That file is ${formatBytes(file.size)}, which is too large for this browser to open in one piece. ` +
              "Nothing is wrong with the export. Split the mbox and import the pieces, or use a smaller date range in Takeout.",
          );
          return;
        }

        await ingest(file.name, text, pass, startedAt);
      } catch {
        if (passRef.current !== pass) return;
        // Clear results too. An error banner sitting over the previous file's
        // rows reads as a verdict on the file that just failed.
        setState(null);
        setError("Couldn't read that file in the browser.");
      } finally {
        // Only the pass that still owns the tab may put the drop zone back at
        // rest; a superseded one would end the newer pass's.
        //
        // BOTH HALVES OF "AT REST" GO IN ONE PLACE, so they cannot land in two
        // React batches. Whatever ended the pass — rows, a refusal, a batch
        // that threw — the field goes with it, because a field left standing
        // beside a stopped pass is the exact thing this work exists to
        // prevent; and clearing the file a batch later would leave one render
        // in which the results are on screen under "Reading your file…".
        if (passRef.current === pass) {
          setPendingFile(null);
          setProgress(null);
        }
      }
    },
    [ingest],
  );

  /**
   * THE DROP ZONE'S LEAD LINE IS THE PAGE'S ONE STATUS SLOT — what it invites,
   * what it is doing, or where the classify pass has got to.
   *
   * It used to be two slots: this line, which said "Drop your mail export
   * here" throughout, and `{busy && <p>reading…</p>}` under the fine print at
   * the bottom of the zone. That is the whisper #390 opens with, and it was in
   * the wrong place twice over — six point type below the least important
   * sentence in the box, and still saying "reading" while the reading was long
   * finished. One slot at the zone's own lead size cannot drift out of step
   * with the state, and because every state fills the same line, none of them
   * moves the box.
   *
   * The numerals are mono because they are counted machine values and the
   * words around them are not; one step down in size, the way the `.mbox`
   * spans below already sit inside their sentence.
   */
  let lead = <>Drop your mail export here</>;
  if (progress) {
    lead = (
      <>
        <span className="tabular font-mono text-sm">{progress.classified}</span> of{" "}
        <span className="tabular font-mono text-sm">{progress.total}</span> classified
      </>
    );
  } else if (pendingFile) {
    lead = <>Reading your file…</>;
  }

  const stats = useMemo(() => {
    if (!state) return null;
    const scanned = state.items.length;
    const heldForReview = state.items.filter((i) => !i.clearsGate).length;
    const autoClassified = scanned - heldForReview;
    const autoPct = scanned === 0 ? 0 : Math.round((autoClassified / scanned) * 100);
    return { scanned, autoClassified, heldForReview, autoPct };
  }, [state]);

  return (
    <div className="space-y-6">
      {/* Drop zone / picker — the page's ONE action, so it leads and it is
          sized like a target, not a form row (#198: "the drop zone is the
          visual centre of the page"). The glyph is an envelope, deliberately
          NOT an upload arrow: nothing here uploads, and the icon must not
          contradict the note below it. `relative` parents the sr-only file
          input. Extensions are set in mono — machine values — while the
          sentence around them stays in the text face. */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void onFile(e.dataTransfer.files?.[0]);
        }}
        className={`relative rounded-xl border border-dashed px-6 py-12 text-center transition-colors sm:py-16 ${
          dragging ? "border-viz-rules bg-surface-2" : "border-line bg-surface"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mbox,.eml,.json,message/rfc822,application/mbox,application/json"
          data-testid="import-file"
          className="sr-only"
          onChange={(e) => void onFile(e.target.files?.[0] ?? undefined)}
        />
        {/* The glyph and the field are the same object at two moments: one
            envelope inviting a file, then one envelope per batch of the mail
            inside it, lighting as the classifier answers. `loading.tsx` draws
            the first of those while the route is pending; this draws the
            second while the work is real. */}
        {progress ? (
          <ClassifyField classified={progress.classified} total={progress.total} />
        ) : (
          <Mail
            aria-hidden="true"
            strokeWidth={1.5}
            className={`mx-auto h-8 w-8 transition-colors ${
              dragging ? "text-viz-rules" : "text-dim"
            }`}
          />
        )}
        <p className="mt-4 text-[15px] font-medium text-strong">{lead}</p>
        {/* The second line answers whatever the first one raised: at rest,
            which formats the zone takes; while a file is in hand, WHICH file —
            "272 of 400 classified" over a list of accepted extensions read as
            though the extensions were the thing being counted. The name is a
            machine value, so it takes the same mono the extensions do. */}
        <p className="mt-1 text-[13px] text-muted">
          {pendingFile ? (
            <span className="font-mono text-xs text-strong">{pendingFile}</span>
          ) : (
            <>
              a Google Takeout <span className="font-mono text-xs text-strong">.mbox</span>, a
              single <span className="font-mono text-xs text-strong">.eml</span>, or a{" "}
              <span className="font-mono text-xs text-strong">.json</span> batch
            </>
          )}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background hover:opacity-90"
          >
            Choose a file
          </button>
        </div>
        <p className="mt-6 text-xs leading-relaxed text-dim">
          Export from Gmail via <span className="text-muted">Google Takeout → Mail</span>. Up to{" "}
          {DEFAULT_MESSAGE_CAP} messages are classified per file to keep the tab responsive.
        </p>
      </div>

      {/* The privacy guarantee — the whole point, said once, at the moment of
          drop. The mechanism detail lives in the policy's "On-device import"
          section this line links to. */}
      <p
        role="note"
        className="rounded-xl border border-viz-rules/25 bg-surface px-4 py-3 text-sm text-muted"
      >
        <span className="text-strong">On-device only.</span> Your file is read and classified
        entirely in this browser tab — the mail never leaves your device.{" "}
        {/* `whitespace-nowrap` because the link was breaking mid-phrase —
            "Privacy" trailing line one, "policy →" orphaned on line two. It is
            one destination, so it wraps as one unit or not at all. And it takes
            the note's own `viz-rules` accent rather than `text-strong`: at
            strong it was the same weight and colour as the "On-device only."
            lead, so the one actionable thing in the box read as more prose. */}
        <a
          href="/privacy#on-device"
          className="whitespace-nowrap text-viz-rules underline-offset-4 hover:underline"
        >
          Privacy policy →
        </a>
      </p>

      {error && (
        <div
          role="alert"
          data-testid="import-error"
          className="rounded-xl border border-reject/40 bg-surface px-4 py-3 text-sm text-strong"
        >
          {error}
        </div>
      )}

      {state && stats && (
        <div className="space-y-5" data-testid="import-results">
          <dl className="grid grid-cols-2 overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-4">
            {(
              [
                ["scanned", String(stats.scanned)],
                ["auto-filed", `${stats.autoClassified} · ${stats.autoPct}%`],
                ["held for review", String(stats.heldForReview)],
                ["source", FORMAT_LABEL[state.format]],
              ] as [string, string][]
            ).map(([k, v]) => (
              <div
                key={k}
                className="border-b border-r border-line-soft p-4 last:border-r-0 sm:border-b-0"
              >
                <dt className="label-caps">{k}</dt>
                <dd className="tabular mt-1 font-mono text-sm font-semibold text-strong">{v}</dd>
              </div>
            ))}
          </dl>

          {/* WHAT HAPPENED TO EVERY MESSAGE, which this line used to get wrong
              in both directions.

              It read: `${totalFound} messages found` plus, only when the cap
              bit, `· classified the first ${items.length}`. Two defects.

              THE CLAUSE WAS FALSE. `items.length` is how many SURVIVED
              parsing, not how many were read, so a 1,000-record file with 300
              blank entries said "classified the first 280" when it had read
              the first 400 and classified 280 of them. Records 281 to 400 were
              read; a reader concludes they were skipped. "The first N"
              describes a prefix, and this was never a prefix.

              AND THE DROPS WERE INVISIBLE BELOW THE CAP. `truncated` is false
              when nothing was trimmed, so a 50-record file that lost 20 to
              unparseable entries printed "50 messages found", listed 30 rows,
              and said nothing at all. That fires on real corpus data too: a
              400-message batch quietly became 393.

              So the line now accounts for every message it claims to have
              found: how many were read, how many produced a verdict, and how
              many did not. Each clause appears only when it is true. */}
          <p className="tabular text-xs text-dim">
            {state.fileName} · {state.totalFound} message{state.totalFound === 1 ? "" : "s"} found
            {state.truncated ? ` · stopped after the first ${DEFAULT_MESSAGE_CAP}` : ""}
            {` · classified ${state.items.length}`}
            {state.unreadable > 0
              ? ` · ${state.unreadable} could not be read and ${state.unreadable === 1 ? "was" : "were"} skipped`
              : ""}
          </p>

          {/* THE FILE'S OWN STRUCTURE WAS AMBIGUOUS, said beside the count it
              qualifies (#426).

              The line above states a number as fact. On an mbox whose bodies
              quote an unescaped `From ` line that number was manufactured:
              five messages were split into ten, and the five phantoms rendered
              in the list below with a subject taken from the quoted text, a
              sender of "(unknown sender)", and the same confidence chrome as
              real mail. `splitMbox` now re-joins those blocks instead of
              inventing rows, and this is where it says the boundary was
              decided rather than read.

              It is a caveat, not an error: nothing was dropped and the rows
              below are real, so it takes the review accent rather than the
              reject one, and it sits under the summary instead of replacing
              the results. `role="status"` because it appears after a file is
              chosen, in response to that choice. */}
          {state.malformed && (
            <p
              role="status"
              data-testid="import-malformed"
              className="rounded-xl border border-review/40 bg-surface px-4 py-3 text-xs leading-relaxed text-muted"
            >
              {state.malformed}
            </p>
          )}

          <div className="overflow-hidden rounded-xl border border-line-soft bg-surface">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line-soft px-4 py-3">
              <span className="flex items-center gap-2 text-xs text-muted">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--viz-rules)" }} />
                layer 1 · rules
              </span>
              <span className="ml-auto flex items-center gap-2 text-xs text-review">
                <span className="inline-block h-2 w-2 rounded-full bg-review" /> below {GATE} → review
              </span>
            </div>
            <ul className="divide-y divide-line-soft">
              {state.items.map((item) => (
                <ImportRow key={item.id} item={item} />
              ))}
            </ul>
          </div>

          <button
            type="button"
            onClick={() => {
              setState(null);
              setError(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
            className="text-xs text-dim underline-offset-4 hover:text-strong hover:underline"
          >
            Clear results
          </button>
        </div>
      )}
    </div>
  );
}
