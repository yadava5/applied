import { BoardDolly } from "./BoardDolly";
import { FollowOneLetter } from "./FollowOneLetter";
import { HeldBreath } from "./HeldBreath";
import { Highlighter } from "./Highlighter";
import { Plate, type PlateInfo } from "./Plate";
import { QuietCase } from "./QuietCase";
import { ReverseCrane } from "./ReverseCrane";
import { MasterShot, RoundTrip } from "./syncTakes";
import { TwentySeconds } from "./TwentySeconds";
import { WhatItKept } from "./WhatItKept";
import { WhereItWaits } from "./WhereItWaits";
import { WorkdayOner } from "./WorkdayOner";

/**
 * The motion lab, round two: the owner picked treatments 01, 02, 03 and 08;
 * everything else is gone. Each pick now stands as a FAMILY of two or three
 * genuinely distinct cinematic variants — different camera logic, not the
 * same move re-eased — on sub-ID plates, so a reply like "build 01b 03a 08c"
 * commissions exact builds. Still a selection surface, not a landing;
 * nothing here ships to `/`.
 *
 * The round's standing rule, owner's words: nothing about how the code is
 * written appears in an exhibit. The old plate 02's pattern/points column is
 * gone, confidence decimals are gone from every exhibit, and what stands
 * beside evidence is CONSEQUENCE — what the product did — never mechanism.
 * (This metadata block below is reviewer scaffolding and may still talk
 * engineering; the ban is about what the exhibits show.)
 *
 * Eleven of twelve plates are choreographed REAL DOM — the shipped
 * components under a camera transform, a synthesized pointer dispatching
 * real events, captions narrating — because real DOM cannot drift from the
 * product. One (03c) is the storyboard for the single shot DOM cannot make.
 */

interface Family {
  id: string;
  title: string;
  note: string;
}

const FAMILIES: Family[] = [
  {
    id: "01",
    title: "The opening act",
    note: "Three cameras on the real board: a working session, a scroll-driven dolly, and a reverse crane out of one line of history. The claim never changes — pick the camera.",
  },
  {
    id: "02",
    title: "Why it decided",
    note: "The lit email survives; the machinery column is gone. What stands beside the evidence now is consequence — the filing, the retention, the case — never the workshop.",
  },
  {
    id: "03",
    title: "The sync story",
    note: "Whole dashboard, the control, a real press, the spinner, what it filed. Two live cameras and one storyboard for the shot DOM can't make. No rejection ever arrives this way — the ambiguous mail lands held, which hands 08 its opening.",
  },
  {
    id: "08",
    title: "Held for review",
    note: "The product's humility, three stagings: the stop as the climax, the human's twenty seconds, and where a held mail actually waits.",
  },
];

const PLATES: PlateInfo[] = [
  {
    id: "01a",
    anchor: "oner",
    title: "The workday oner",
    fidelity: "live",
    argues:
      "One continuous session: the pulse's real filed-on-a-date filter, the board narrowing with its own glide, a row opening, its history docking, the filter clearing. The camera follows the reading, not the pointer.",
    costs:
      "Zero media; the take engine (shared by six plates) plus this script. Risk: selector drift if board labels change — the take fails loudly and its caption says so.",
    lie: "Staging a dropdown the product does not have. The date filter here is the shipped pulse panel's own day bar — no control is drawn for the camera.",
    honest:
      "Every event is dispatched at the shipped component; the survivors of the filter are whoever the real filter leaves. Drag a card mid-take and the board answers you, not the script.",
  },
  {
    id: "01b",
    anchor: "dolly",
    title: "The dolly",
    fidelity: "live",
    argues:
      "Scroll as the camera: rise to product scale, travel down three stages of real cards, and at the foot the act's own verdict plays — the offer moves its row, the pane docks.",
    costs:
      "Zero media; rides MarketingBoard's existing verdict/docked machinery. Risk: runway height wants the usual 1024 measure before shipping.",
    lie: "A timeline that keeps playing after the reader's hand stops. This is position, not time — it cannot outrun the scroll.",
    honest:
      "State is a function of scroll position; scroll up and the verdict un-happens, the landing act's own reversibility rule.",
  },
  {
    id: "01c",
    anchor: "crane",
    title: "Start at the end",
    fidelity: "live",
    argues:
      "A reverse crane: open on ONE line of one mail trail, pull back until the whole board holds it. The record is the product's point, so the record is the establishing shot.",
    costs: "Zero media; one script. Risk: none new — the pane is opened by a real click before the shot settles.",
    lie: "Composing a 'history' for the shot. The trail in frame is the pane's own, loaded by the shipped transport.",
    honest:
      "The camera pulls out of a state the product built for itself; every intermediate frame is the real pane beside the real list.",
  },
  {
    id: "02a",
    anchor: "highlighter",
    title: "The highlighter",
    fidelity: "live",
    argues:
      "A reading light sweeps the mail once; the deciding phrases catch and hold at the recorded offsets; the verdict stamps; and beside it the consequence plays — the real board row flips its stage.",
    costs: "Zero media. Risk: none found; the grammar is substrate for 02b and 03c.",
    lie: "The sweep passing itself off as the classifier's runtime. It is staging — the verdict and spans are computed before the bar moves, and the exhibit's own caption says so.",
    honest:
      "Spans recorded during the scoring walk, in this tab; the panel beside the mail shows what HAPPENED — never a pattern, a weight, or a decimal.",
  },
  {
    id: "02b",
    anchor: "kept",
    title: "What it kept",
    fidelity: "live",
    argues:
      "Retention enacted: the mail dissolves — unlit prose first, then even the lit phrases, because they were read and used, never stored — and what remains is the record the database actually holds.",
    costs: "Zero media; the kept-record grammar already ships on the landing's retention exhibit.",
    lie: "Letting the dissolve read as deleting mail from Gmail. The captions pin it to Applied's copy, inside Applied's frame; Gmail keeps the original.",
    honest:
      "The record shown is the real retained shape — subject, sender, an 80-char snippet, the verdict, body columns never written — and the deciding sentence is demonstrably not in it.",
  },
  {
    id: "02c",
    anchor: "quiet-case",
    title: "The quiet case",
    fidelity: "live",
    argues:
      "The restrained option: phrases light one at a time, each quoted verbatim beside the mail, verdict last. Evidence, then conclusion, at reading pace.",
    costs: "Zero media. Risk: none found.",
    lie: "Quoting phrases the engine never scored. The quotes are sliced at the recorded offsets, so a rules change re-lights and re-quotes the exhibit in the same render.",
    honest: "The mail's own words are the whole display — what decided, never how deciding is written.",
  },
  {
    id: "03a",
    anchor: "round-trip",
    title: "The round trip",
    fidelity: "live",
    argues:
      "The owner's spec, staged: wide, in to the Sync control, a real press — then OUT while the spinner runs, so the wait becomes anticipation and the payoff lands in the wide shot: two confirmations file, the totals move, and one ambiguous mail lands amber in the tray.",
    costs:
      "Zero media; a lab-owned mount (LabSyncBoard) wiring the shipped SyncBar + board + queue over the showcase fixture, because /demo's fixtures are e2e geometry and must not move for a marketing lab.",
    lie: "Captioning the pass as classification — the simulated sync commits pre-labelled rows, so every caption stays scoped to what it FILED. And a rejection arriving by sync: production has never auto-filed one, so the pool never contains one.",
    honest:
      "The press is a real press; the run, receipt, new totals and held arrival are the shipped components' own doing, and replay remounts to the product's initial state.",
  },
  {
    id: "03b",
    anchor: "master-shot",
    title: "The master shot",
    fidelity: "live",
    argues:
      "The contrarian camera: one fixed frame, no moves. The product's own motion — the running state, the arrivals' glide, the tray appearing — is the entire effect.",
    costs: "Zero media; same mount as 03a, a shorter script.",
    lie: "Same two as 03a — the caption scope and the no-rejection rule — plus any cut that compresses the wait: the spinner runs at its real duration.",
    honest: "If the take is boring, the product is boring — nothing here can hide it, which is the argument for it.",
  },
  {
    id: "03c",
    anchor: "one-letter",
    title: "Follow one letter",
    fidelity: "storyboard",
    argues:
      "The tracking shot DOM cannot make: the camera locks one arrival, it unfolds mid-flight into the mail, the reading light sweeps it, it folds into a board row and rides down into its group.",
    costs:
      "One Remotion render (free tier covers this repo) + amending the footage README's cursor covenant in plate 05's recorded-events terms — anything synthesized is synthesized at capture time from the real events, and disclosed. That amendment is part of this plate's price, not a footnote.",
    lie: "The in-flight reading implying the sync frame classified live, or the tracked letter being a rejection. Both are written into the shot list as refusals.",
    honest: "Stamped until rendered: no motion is faked on this plate — the storyboard is cards, not a canned animation.",
  },
  {
    id: "08a",
    anchor: "held-breath",
    title: "The held breath",
    fidelity: "live",
    argues:
      "Two mails file fast — tick, tick — then the third stops the room: the filed cards dim, an amber ring draws over a full second, and it settles as held with NO guess shown. The stop is the climax.",
    costs:
      "Zero media. Risk: the trio's split depends on rules.json — if the rules move, the cards re-verdict themselves; re-check the composition after rule changes.",
    lie: "Printing the held card's top guess — writing a verdict where the product's answer is the typed null forges the human decision it refuses to make. The old plate showed the guess; this one does not.",
    honest: "All three verdicts computed live at render; the held card commits nothing, in the product's own words.",
  },
  {
    id: "08b",
    anchor: "twenty-seconds",
    title: "Twenty seconds on a Tuesday",
    fidelity: "live",
    argues:
      "The human's half of the loop, on the real queue: an obvious-to-a-person rejection the machine honestly couldn't read from a snippet, and the pointer stopping AT the decision — because the next click is the product.",
    costs:
      "Zero media today. The full clear-the-tray cut needs a classify seam in the queue row (it POSTs straight to the API) — a product improvement the demo twin already wants; commissioning 08b in full includes it.",
    lie: "The take 'filing' the row — forging the one decision this surface reserves for a person. The take ends at the boundary instead, and says so.",
    honest:
      "Both held mails are cast mails with live-computed confidences behind the real rows; the rejection-in-the-tray IS the production truth of how rejections reach the board.",
  },
  {
    id: "08c",
    anchor: "where-it-waits",
    title: "Where it waits",
    fidelity: "live",
    argues:
      "The mail's journey, not the human's: Cedar's held note settles into the real review queue beneath it — nothing vanishes, nothing is guessed, the question stays open on the board.",
    costs: "Zero media. Risk: none found.",
    lie: "A held mail 'disappearing' into a tray the product doesn't have. The tray is the shipped ReviewQueue over the showcase rows.",
    honest: "The same mail 08a refused to judge is the queue's first row — one cast, one story, across the family.",
  },
];

export function MotionLab() {
  return (
    <main className="min-h-screen bg-background text-muted">
      <header className="mx-auto w-full max-w-5xl px-6 pb-10 pt-16">
        <p className="label-caps">Applied · motion lab · round two · not linked, not indexed</p>
        <h1 className="mt-3 max-w-2xl text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          Twelve takes on the four treatments you picked.
        </h1>
        <p className="mt-4 max-w-2xl">
          Each family stages the same claim with genuinely different cameras. Eleven plates are
          live — real components under a camera, a pointer the page drives, a real press wherever
          something is pressed — and one is the storyboard for the shot DOM can&apos;t make. Reply
          with sub-IDs to commission builds — e.g.{" "}
          <span className="font-mono text-sm text-strong">build 01a 03a 08a</span>.
        </p>
        <p className="mt-3 max-w-2xl text-sm text-dim">
          House rule this round, per your ban: no exhibit shows patterns, weights, confidence
          decimals or anything about how the engine is written. Evidence is the mail&apos;s own
          words; what stands beside it is what the product did.
        </p>

        <nav aria-label="Plates" className="mt-8 overflow-hidden rounded-xl border border-line-soft">
          <ul className="text-sm">
            {FAMILIES.map((family) => (
              <li key={family.id} className="border-b border-line-soft last:border-b-0">
                <p className="label-caps bg-surface px-4 pb-1.5 pt-2.5">
                  {family.id} · {family.title}
                </p>
                <ul className="divide-y divide-line-soft">
                  {PLATES.filter((p) => p.id.startsWith(family.id)).map((p) => (
                    <li key={p.id}>
                      <a
                        href={`#${p.anchor}`}
                        className="flex items-baseline gap-4 px-4 py-2.5 transition-colors hover:bg-surface"
                      >
                        <span className="font-mono text-sm text-viz-rules">{p.id}</span>
                        <span className="min-w-0 flex-1 truncate text-strong">{p.title}</span>
                        <span
                          className={`label-caps shrink-0 ${
                            p.fidelity === "live" ? "text-viz-rules" : "text-review"
                          }`}
                        >
                          {p.fidelity === "live" ? "live" : "storyboard"}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      {FAMILIES.map((family) => (
        <section key={family.id} aria-label={`Treatment ${family.id} — ${family.title}`}>
          <div className="border-t border-line">
            <div className="mx-auto w-full max-w-5xl px-6 pb-2 pt-12">
              <p className="label-caps">treatment {family.id}</p>
              <h2 className="mt-2 text-2xl font-medium tracking-tight text-strong">
                {family.title}
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-relaxed text-dim">{family.note}</p>
            </div>
          </div>
          {PLATES.filter((p) => p.id.startsWith(family.id)).map((info) => (
            <Plate key={info.id} info={info}>
              {EXHIBITS[info.id]}
            </Plate>
          ))}
        </section>
      ))}

      <footer className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-12 text-sm text-dim">
          <p>
            Pick by sub-ID — <span className="font-mono text-strong">build 01a 03a 08a</span> — or
            name a plate to argue with. The storyboarded plate (03c) needs a footage run before it
            can be judged as motion; everything stamped live is running on this page, and replaying
            a take remounts the product to its own initial state.
          </p>
        </div>
      </footer>
    </main>
  );
}

const EXHIBITS: Record<string, React.ReactNode> = {
  "01a": <WorkdayOner />,
  "01b": <BoardDolly />,
  "01c": <ReverseCrane />,
  "02a": <Highlighter />,
  "02b": <WhatItKept />,
  "02c": <QuietCase />,
  "03a": <RoundTrip />,
  "03b": <MasterShot />,
  "03c": <FollowOneLetter />,
  "08a": <HeldBreath />,
  "08b": <TwentySeconds />,
  "08c": <WhereItWaits />,
};
