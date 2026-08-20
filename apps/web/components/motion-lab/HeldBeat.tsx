"use client";

// The bar is imported from the surface that owns it — ImportMail is a client
// module, so this file carries the directive too (a server component would
// receive a client REFERENCE for the constant; see footage.ts for the scar).
import { RULES_ACCEPT } from "@/components/import/ImportMail";
import { classifyWithRules } from "@/lib/demo/rulesLayer";

/**
 * Candidate 08 — the held-for-review beat: three synthetic mails, three live
 * verdicts, one held.
 *
 * Every verdict below is computed in this tab by the shipped rules layer at
 * render — nothing is hardcoded, and the "held" card commits NO category:
 * under the accept bar the product's answer is the typed null (needs
 * review), so this exhibit shows a top guess and the bar it fell short of,
 * in the same words /import uses. The bodies were tuned against rules.json
 * (2026-08-19) so the trio lands two-over-one-under; if the rules change,
 * the cards re-verdict themselves and the layout follows the engine.
 *
 * Why it belongs on a landing: 0.979 with no visible miss reads as "too
 * good". A held verdict is the product's humility shown working — the
 * classifier saying "not sure" instead of guessing.
 *
 * Pure and date-free → prerender-safe, same result on server and client.
 */

const TRIO = [
  {
    subject: "Update on your application to Meridian Grid",
    sender: "recruiting@meridiangrid.dev",
    body: "Hi Ayush, thank you for taking the time to interview with us. After careful consideration, we have decided to move forward with other candidates for this role. We were impressed by your background and encourage you to apply again in the future.",
  },
  {
    subject: "Next step: online assessment for Kestrel Dynamics",
    sender: "no-reply@hire.lever.co",
    body: "Hi Ayush, as the next step in your application we would like you to complete an online coding assessment. The HackerRank test takes about 90 minutes and must be completed within 5 days. Good luck!",
  },
  {
    subject: "Quick follow-up from Cedar Labs",
    sender: "team@cedarlabs.io",
    body: "Hi Ayush, a quick note from our side — the review is taking a little longer than planned this cycle. Nothing is needed from you right now, and we appreciate your patience.",
  },
] as const;

export function HeldBeat() {
  return (
    <div>
      <div className="grid gap-4 lg:grid-cols-3">
        {TRIO.map((mail) => {
          const v = classifyWithRules(mail.subject, mail.body, mail.sender);
          const clears = v.confidence >= RULES_ACCEPT;
          return (
            <article
              key={mail.subject}
              className={`flex flex-col overflow-hidden rounded-xl border bg-surface ${
                clears ? "border-line-soft" : "border-review/40"
              }`}
            >
              <div className="border-b border-line-soft px-4 py-3">
                <p className="text-sm font-medium text-strong">{mail.subject}</p>
                <p className="mt-0.5 font-mono text-xs text-dim">{mail.sender}</p>
              </div>
              <p className="flex-1 px-4 py-3 text-[0.8125rem] leading-relaxed text-muted">
                {mail.body}
              </p>
              <div className="border-t border-line-soft px-4 py-3">
                {clears ? (
                  <>
                    <p className="flex items-center gap-2">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
                      <span className="text-sm font-medium text-strong">{v.category}</span>
                      <span className="tabular font-mono text-xs text-dim">
                        {v.confidence.toFixed(2)}
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-dim">
                      clears the accept bar (≥ {RULES_ACCEPT.toFixed(2)}) — rules answer alone
                    </p>
                  </>
                ) : (
                  <>
                    <p className="flex items-center gap-2">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-review" />
                      <span className="text-sm font-medium text-review">held for review</span>
                      <span className="tabular font-mono text-xs text-dim">
                        {v.confidence.toFixed(2)}
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-dim">
                      top guess &ldquo;{v.category}&rdquo; — below the {RULES_ACCEPT.toFixed(2)} bar,
                      so no verdict is written; a human decides
                    </p>
                  </>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <p className="mt-4 max-w-2xl text-xs leading-relaxed text-dim">
        Synthetic mails; live verdicts from the shipped rules layer, computed at render. The held
        card commits no category — under the bar the answer is &ldquo;a human decides&rdquo;, which
        is what keeps 0.979 believable.
      </p>
    </div>
  );
}
