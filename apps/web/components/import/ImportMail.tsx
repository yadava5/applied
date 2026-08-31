"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { Mail } from "lucide-react";

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

function classify(messages: ParsedMessage[]): Classified[] {
  return messages.map((m) => {
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
  });
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

export function ImportMail() {
  const [state, setState] = useState<ImportState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const ingest = useCallback((fileName: string, text: string) => {
    setError(null);
    try {
      const result = parseMailFile(fileName, text);
      if (result.messages.length === 0) {
        setState(null);
        setError(
          "No messages found in that file. Expected a Google Takeout .mbox, a single .eml, or a JSON array of { subject, from, body }.",
        );
        return;
      }
      setState({
        fileName,
        format: result.format,
        totalFound: result.totalFound,
        truncated: result.truncated,
        unreadable: result.unreadable,
        items: classify(result.messages),
      });
    } catch (err) {
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
  }, []);

  const onFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      setBusy(true);
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

        ingest(file.name, text);
      } catch {
        // Clear results too. An error banner sitting over the previous file's
        // rows reads as a verdict on the file that just failed.
        setState(null);
        setError("Couldn't read that file in the browser.");
      } finally {
        setBusy(false);
      }
    },
    [ingest],
  );

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
        <Mail
          aria-hidden="true"
          strokeWidth={1.5}
          className={`mx-auto h-8 w-8 transition-colors ${
            dragging ? "text-viz-rules" : "text-dim"
          }`}
        />
        <p className="mt-4 text-[15px] font-medium text-strong">Drop your mail export here</p>
        <p className="mt-1 text-[13px] text-muted">
          a Google Takeout <span className="font-mono text-xs text-strong">.mbox</span>, a single{" "}
          <span className="font-mono text-xs text-strong">.eml</span>, or a{" "}
          <span className="font-mono text-xs text-strong">.json</span> batch
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
        {busy && <p className="mt-2 text-xs text-dim">reading…</p>}
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
