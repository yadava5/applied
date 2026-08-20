import { ArtifactF1, type DerivedF1 } from "./ArtifactF1";
import { ClipScaleFix } from "./ClipScaleFix";
import { CursorStoryboard } from "./CursorStoryboard";
import { EstablishingZoom } from "./EstablishingZoom";
import { HeldBeat } from "./HeldBeat";
import { Plate, type PlateInfo } from "./Plate";
import { ProvenanceReceipt } from "./ProvenanceReceipt";
import { PulseExhibit } from "./PulseExhibit";
import { RulesTraceExhibit } from "./RulesTraceExhibit";
import { SpineDemo } from "./SpineDemo";
import { SyncRailRefill } from "./SyncRailRefill";

/**
 * The motion lab: ten candidate motion treatments for the landing, each on a
 * numbered plate, so the owner can look and reply with IDs instead of
 * commissioning builds he might not want. A selection surface, not a
 * landing — nothing here ships to `/`.
 *
 * Plate numbering follows the brief's own list 1:1, so a reply like
 * "build 02, 06, 09" is unambiguous against it.
 */

const PLATES: PlateInfo[] = [
  {
    id: "01",
    anchor: "zoom",
    title: "Establishing zoom on the opening act",
    fidelity: "live",
    argues: "Show the whole pipeline in one frame first, then arrive at product scale.",
    costs: "Zero bytes of media, ~30 lines in WindowAct. No new risk — it rides the act's existing scrub.",
    lie: "It can't, structurally: there is no recording to re-time or recompose.",
    honest: "Real DOM at every frame — drag a card mid-zoom and it answers.",
  },
  {
    id: "02",
    anchor: "trace",
    title: "Rules-trace highlight on the verdict email",
    fidelity: "live",
    argues: "The differentiator itself: the spans that decided, lit by the engine that decided.",
    costs: "Zero bytes. One engine change (a recorder on the shipped walk — done, see rulesLayer.ts). Risk: none found.",
    lie: "A marketing component re-running its own regexes would drift from the verdict the moment rules.json moved.",
    honest: "The offsets are recorded DURING scoring, in the same walk — the display cannot disagree with the verdict.",
  },
  {
    id: "03",
    anchor: "sync-rail",
    title: "Refilling the sync rail",
    fidelity: "live",
    argues: "The one genuinely empty exhibit: give 1114px of pin the whole retention sentence — the reading, then the kept record.",
    costs: "Zero bytes (both exhibits already ship). A tempo edit in ClaimsDescent. Risk: rail height at short viewports needs the usual 1024 measure.",
    lie: "Captioning the sync clip as classification — the demo's Sync classifies nothing, it commits pre-labelled fixture rows.",
    honest: "The caption stays scoped to the pass (\"what it filed\"); the classification evidence sits in the kept record beside it, computed live.",
  },
  {
    id: "04",
    anchor: "clip-scale",
    title: "Fixing the import clip's scale",
    fidelity: "live",
    argues: "The page's worst-read exhibit at 0.64× product scale — see the fix at real size before paying for it.",
    costs: "Option A: free, a width token. Option B: one footage run (~build + capture + encode). Risk: A is bounded by the encode; B re-stages a take the owner already approved once.",
    lie: "\"Bigger\" past the 576 ceiling shows mush as detail — upscaling claims sharpness the encode doesn't hold.",
    honest: "Every scale factor below is computed from the authored crop and the encode's real width; the ceiling is stated, not exceeded.",
  },
  {
    id: "05",
    anchor: "cursor",
    title: "Cursor pane-walk",
    fidelity: "storyboard",
    argues: "The one thing no clip shows yet: the product being USED — a real pointer opening the row, the pane docking, the trail scrolling.",
    costs: "One footage run + amending the footage README's cursor rule + @remotion/mac-cursors (free tier covers this repo). Risk: the amendment itself — see the frame.",
    lie: "A cursor drawn over frames in post, or a 4-second operation quietly played at 1s — compression that changes the claim.",
    honest: "Cursor synthesized at capture time from the real events that drove the take, disclosed in the README; dead time cut in whole segments and disclosed, never re-timed.",
  },
  {
    id: "06",
    anchor: "receipts",
    title: "Provenance receipts under every clip",
    fidelity: "live",
    argues: "The page's honesty made visible: each recording carries its own manifest-sourced receipt, never typed.",
    costs: "Zero bytes beyond text. One-line render.mjs change to add route + commit fields. Risk: none found.",
    lie: "A hand-typed caption drifts into fiction the first time a clip is re-rendered and the words aren't.",
    honest: "Every value is read from manifest.json, which the encoder wrote; missing fields stay missing until the pipeline writes them.",
  },
  {
    id: "07",
    anchor: "pulse",
    title: "Live micro-exhibit: the pulse band",
    fidelity: "live",
    argues: "Small boxes as live computation, not video: the product's own pulse over the showcase fixture, at your clock.",
    costs: "Zero bytes of media; the dashboard chunk (already paid by the board embed). Risk: fixture must keep feeding every cell honestly (see showcase.ts's burst-shaped dates).",
    lie: "A fixture shaped to flatter a chart — one filing per day once drew a picket fence that read as fake.",
    honest: "The shipped component computes every number at mount; the fixture is the same burst-shaped seed the live board uses, provenance stated.",
  },
  {
    id: "08",
    anchor: "held",
    title: "The held-for-review beat",
    fidelity: "live",
    argues: "The product's humility, shown working: three live verdicts, one held under the bar — it inoculates 0.979 against \"too good\".",
    costs: "Zero bytes. Risk: the trio's split depends on rules.json — if the rules move, the cards re-verdict themselves (that is the point, but re-check the composition after rule changes).",
    lie: "Writing the held card's top guess as its verdict — forging the human decision the product deliberately refuses to make.",
    honest: "All three verdicts computed live at render; the held card commits no category, in /import's own words.",
  },
  {
    id: "09",
    anchor: "spine",
    title: "A travelling spine in the gutter",
    fidelity: "live",
    argues: "One element that never resets: the page's alternation made watchable, ticking machine values it does not own.",
    costs: "Zero bytes, one fixed-position element on the landing. Risk: another always-on scroll listener (cheap next to the existing scrubs), and it must never carry a number of its own.",
    lie: "The spine inventing a figure at a handoff — a number that cannot be derived in a gate does not go on a marketing page.",
    honest: "Every tick is imported from copy.ts / verdictEmailData.ts, the same single sources the landing's claims read.",
  },
  {
    id: "10",
    anchor: "f1-gate",
    title: "ClassF1Bars sourced from the artifact",
    fidelity: "live",
    argues: "The per-class figure already ships hand-typed and ungated — here it is derived from the evaluation artifact and diffed against itself.",
    costs: "A build-time sync script + CI gate (readme-facts idiom). Risk: none — correct today, and the gate is what keeps it correct.",
    lie: "Nothing fails today if the benchmark moves: the bars would keep announcing a number the artifact no longer holds.",
    honest: "The equality below is computed at render from the artifact the headline is transcribed from — and the gate makes drift a CI failure.",
  },
];

const EXHIBITS: Record<string, React.ReactNode> = {
  "01": <EstablishingZoom />,
  "02": <RulesTraceExhibit />,
  "03": <SyncRailRefill />,
  "04": <ClipScaleFix />,
  "05": <CursorStoryboard />,
  "06": <ProvenanceReceipt />,
  "07": <PulseExhibit />,
  "08": <HeldBeat />,
  "09": <SpineDemo />,
};

export function MotionLab({
  derivedF1,
  macroF1,
  generatedAt,
}: {
  derivedF1: DerivedF1[];
  macroF1: number;
  generatedAt: string;
}) {
  return (
    <main className="min-h-screen bg-background text-muted">
      <header className="mx-auto w-full max-w-5xl px-6 pb-10 pt-16">
        <p className="label-caps">Applied · motion lab · not linked, not indexed</p>
        <h1 className="mt-3 max-w-2xl text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          Ten motion treatments, working where they can and stamped where they can&apos;t.
        </h1>
        <p className="mt-4 max-w-2xl">
          Each plate shows the treatment itself, what it argues, what it costs, and the specific
          way it could lie. Reply with plate IDs to commission builds — e.g.{" "}
          <span className="font-mono text-sm text-strong">build 02 06 09</span>.
        </p>

        <nav aria-label="Plates" className="mt-8 overflow-hidden rounded-xl border border-line-soft">
          <ul className="divide-y divide-line-soft text-sm">
            {PLATES.map((p) => (
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
        </nav>
      </header>

      {PLATES.map((info) => (
        <Plate key={info.id} info={info}>
          {info.id === "10" ? (
            <ArtifactF1 derived={derivedF1} macroF1={macroF1} generatedAt={generatedAt} />
          ) : (
            EXHIBITS[info.id]
          )}
        </Plate>
      ))}

      <footer className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-12 text-sm text-dim">
          <p>
            Pick by ID — <span className="font-mono text-strong">build 02 06 09</span> — or name a
            plate to argue with. Storyboarded plates need a footage run before they can be judged
            as motion; everything stamped live is running on this page.
          </p>
        </div>
      </footer>
    </main>
  );
}
