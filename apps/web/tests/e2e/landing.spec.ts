import { expect, test, type Locator, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";
import { ACT, HELD_TAKE, KEPT } from "../../components/marketing/copy";

/**
 * E2E for the landing (`/`) — the pinned-scroll composition, which was
 * promoted here from `/landing-b` once the owner chose it.
 *
 * WHY THIS FILE EXISTS. The page's honesty guarantees are GEOMETRIC, and the
 * unit gate (`landing-variants.test.mjs`) is a source scan that cannot see a
 * pixel. The two standing guarantees:
 *
 *  1. THE PROVENANCE LINE — the descent exhibit's last sentence ("A synthetic
 *     email — the verdicts are computed live in this tab…") stays inside the
 *     fold at the shortest supported viewport, in the stage where the
 *     verdicts are on screen.
 *  2. THE RAIL PIN — every pinned rail holds at its sticky offset for at
 *     least `MIN_PIN_SHARE` of its own band, at the six corner viewports of
 *     the design range. Do not weaken this to fit an exhibit; reshape the
 *     exhibit.
 *
 * THE SCRUBBED WINDOW ACT'S SUITE RETIRED WITH THE ACT (2026-08-20). The
 * offer choreography — camera pan, receipt, verdict latch, seeded pane, the
 * reversal contract — was replaced by the workday oner (`WindowAct` /
 * `OnerStage`: a director-driven take on its own pausable clock, the closing
 * act's pin-and-play mechanism), so the seven tests that drove its marks
 * went with it: their subject no longer exists. Git history holds them, with
 * their mutation evidence, should the choreography ever be recalled. What
 * covers the oner now is the take trio below (autoplay + narration, the
 * pause control, reduced-motion disarm). They were WRITTEN BLIND, in a
 * session that could not run Playwright, and that history is kept rather
 * than tidied away because it is how a false mutation recipe got into this
 * file. The debt is now discharged: all three have been watched go red on a
 * named mutation and green again on the restored file (2026-08-20), and
 * each recipe now sits at the assertion it actually reddens rather than one
 * standing for a group — a group recipe is what hid a double-gated
 * assertion here. Where a line rides on the assertion above it (`expect`
 * fails fast, so it is evaluated but never watched red), that is named
 * rather than claimed as coverage.
 *
 * THE RACE GATE RETIRED WITH THE SAME CHOREOGRAPHY (2026-08-20, one commit
 * later — its `-g` filter matched two of the deleted tests and correctly
 * failed loud on an empty run). `.github/workflows/landing-b-race.yml`
 * guarded whether `MarketingBoard` reads a visitor's own card open as the
 * page's: a 0ms load timer racing a claim armed from an observer-driven
 * commit. That race needs the claim ARMED, and no mount passes
 * `verdict`/`docked` any more, so `pendingSeedRef` is written nowhere and
 * the guarded branch compares against permanently-undefined. The oner has
 * no equivalent: the one hand-vs-page classification it makes rides
 * `event.isTrusted` — synchronous and unforgeable, chosen precisely to
 * remove the timing dimension — and with no claim to spend, both outcomes
 * of the old gesture-window check converge to identical observable
 * behaviour. The workflow's header (last at 9e1675c) carries measured
 * sensitivity work — p = 0.8% per attempt on ubuntu-latest at --workers=4,
 * ~16x below a laptop, n sized from it — that must come back WITH the
 * workflow if the offer beat is ever recalled: recalling the beat re-arms
 * the claim, and the race is real again the same day.
 *
 * WHY PRODUCTION-ONLY. `next dev` re-renders every route per request and
 * this page is a static prerender whose board mounts client-side; a dev run
 * has already produced false reds on a clean commit here. Same gate and
 * mechanism as `production.spec.ts`.
 *
 * MUTATION HISTORY. The surviving tests' evidence stands: the provenance
 * crops (`py-6`→`py-16`, 37.1px below the fold), the rail-pin collapses
 * (12/12 red, one rail at a time, four viewports), the closing act's
 * playhead and seat, and the overflow trio are all recorded in git history
 * with the runs that reddened them.
 */

const PROD_BUILD = process.env.PLAYWRIGHT_PROD_BUILD === "1";

/** The shortest desktop viewport this page is designed for — the tight case:
 *  the descent's exhibit clears 600px by single-digit pixels. */
const DESKTOP_1024 = { width: 1024, height: 600 };
/** The other height the page is verified at — a second amount of stage room
 *  for the pinned exhibits and the take's frame. */
const DESKTOP_1024_768 = { width: 1024, height: 768 };
/** A tall desktop, and the reason the pin is measured at more than one height.
 *  Rail geometry is `dvh`-paced on one axis and fixed on the other — the
 *  exhibits are a fixed number of pixels tall in a fixed-width column — so the
 *  ratio the pin gate watches MOVES with the viewport, and it does not move
 *  monotonically: a short viewport squeezes the rail against its own exhibit,
 *  a tall one against its phase's runway. #access — a rail this page no
 *  longer has — read 0.262 at 1024x768 and 0.170 at this height on the same
 *  build, so a gate fixed at one height was structurally unable to see the
 *  failure. The review rail — the five-rail spine's tightest — squeezes by
 *  the same mechanism, so the height corners matter MORE than they did. */
const DESKTOP_1512 = { width: 1512, height: 949 };
/** WIDE AND SHORT, and the reason the pin is measured at more than one WIDTH.
 *  This was where the tightest pin on the page lived — #access at 0.213 —
 *  and until 2026-08-19 no walk had ever visited it: width moves a rail by a
 *  different mechanism than height does, so a set of heights at one width
 *  cannot see it. #access is gone (see `STICKY_EXHIBIT`), which removes the
 *  reading, NOT the mechanism: passing 1280 still grows every clip exhibit by
 *  4px (`ProductClip`'s figcaption takes `xl:pt-1`) while a narrower column
 *  wraps its band's prose longer, so the two axes still trade against each
 *  other and a single-width set still could not see it. The corner stays
 *  walked — and it matters MORE since the fluid spread (2026-08-20): rail
 *  widths now ramp with vw between 1024 and 1512 (`ClaimsDescent`), so width
 *  moves every exhibit's height continuously, not by one 4px breakpoint
 *  step. 1512 is where the owner works AND where the ramp tops out; widths
 *  past 1512 read the same, the composition capping at its 85rem gutter. */
const DESKTOP_1512_600 = { width: 1512, height: 600 };
/** TALL, and the reason the pin is measured above 949 — permanently. The
 *  walked set has now been chosen after the measurement THREE times, and each
 *  time the blind spot sat one corner past the set: dc1bdee walked 768 alone
 *  and missed 949; a47d8e0 walked three viewports and missed wide-and-short;
 *  and the take rework's set topped out at 949 and missed TALL — the decision
 *  rail's viewport-tall box grows 1:1 with dvh, so a band that is not
 *  dvh-paced loses runway linearly with height, and the collapse began at
 *  ~1075px: 0.305 at 949, 0.191 at 1512×1080, 0.110 at 2560×1440, invisible
 *  to every walked corner. A 1080p fullscreen is not an exotic viewport; it
 *  is the most common desktop there is. So the tall edge is a standing
 *  corner now: 1512×1080 (the fullscreen anyone actually has) and 1024×1120
 *  (the owner's 1024-wide discipline on a tall screen — narrow wraps the
 *  band's prose longer, so the two tall cases squeeze by different
 *  mechanisms, same as the short pair). */
const DESKTOP_1512_1080 = { width: 1512, height: 1080 };
const DESKTOP_1024_TALL = { width: 1024, height: 1120 };
const TABLET_768 = { width: 768, height: 1024 };

/**
 * The exhibit's closing sentence — the honesty guarantee, matched on the two
 * clauses that carry it rather than on the whole sentence, so a wording tweak
 * that keeps the promise does not turn CI red.
 *
 * IT DID TURN CI RED, on 2026-08-21, over ONE CHARACTER. The pattern demanded
 * a literal space after "email", and the copy sweep changed
 *
 *     "A synthetic email — the verdicts are computed live in this tab by the
 *      shipped rules layer."
 *     "A synthetic email. The verdicts are computed live in this tab."
 *
 * which keeps the promise exactly and drops only the internals name. So the
 * regex failed its own stated intent, one line above itself. `\b[\s\S]*` now
 * spans whatever punctuation sits between the two clauses.
 *
 * THE STRUCTURAL POINT IS WORTH MORE THAN THE FIX. This was the THIRD time
 * this test's containment block has been disarmed by a fail-fast locator
 * upstream of it, and the docblock below documents the first two itself. Ten
 * or so assertions gate the one that matters, so a copy edit anywhere in the
 * drive stops the guarantee being checked at all — and the failure that
 * reaches you says "locator not found", which invites loosening the locator
 * rather than asking whether the guarantee still holds.
 *
 * SO ASK, every time. On this occasion it did hold: measured 7.19px of
 * clearance against a 600px fold, matching the 7.2px this file records as
 * canonical. A loosened locator with an unmeasured guarantee behind it is a
 * check that cannot fail.
 *
 * Deliberately still addressed by the words the reader sees, not by a
 * test-only attribute. A hook here would be a knob rather than a measurement,
 * and the thing under test is what a reader can actually see in the frame.
 */
const PROVENANCE = /A synthetic email\b[\s\S]*computed live in this tab/;

/** A pinned rail (`lg`+ only) — the page's spine is five of them since the
 *  2026-08-20 restaging (`RAIL_COUNT` names them), sides alternating
 *  (`ClaimsDescent`'s docblock). Before that it was three, briefly four:
 *  `#access` pinned the import recording until that clip was retired on
 *  2026-08-20, and with nothing honest to pin the phase collapsed to a
 *  single column rather than borrow an exhibit (`AccessPhase` argues it).
 *  Below `lg` each screen carries its own inline snapshot, and those are
 *  the copies this must NOT measure.
 *
 *  It used to be `div.sticky.top-20`, and that stopped being a description of
 *  the spine: the clip rails resolve their sticky offset from the
 *  viewport and their own exhibit's height (`top-[max(5rem,…)]`), because a
 *  viewport-tall box left its phase no runway to pin across. A utility class
 *  was never the right handle anyway — it made a rail's identity a styling
 *  detail, so a rail could leave this count by being restyled rather than by
 *  being unstaged. `data-rail` names the phase and is what a rail losing its
 *  staging actually removes. */
const STICKY_EXHIBIT = "[data-rail]";
/** How many rails the spine runs at `lg`+ since 2026-08-20 (the owner's
 *  "five or six boxes aside from the oner"): verdict (right, the 02b take),
 *  rules (left, the big box), review (right, the 08c take), row (left, the
 *  tracked recording), retention (right). A sixth means a phase forked its
 *  staging — or that `#access` grew a rail back, which needs a recording,
 *  not a rearrangement; four means one dropped out of the language the page
 *  was chosen for. */
const RAIL_COUNT = 5;

/** How close to the sticky offset a sample has to read to count as PINNED.
 *  The plateau measured exactly 80px at 1024x768, but a 1px rounding drift
 *  has shown up on another probe of the same rails, so this is a tolerance
 *  and not an equality. It is deliberately far below `PIN_STEP`: a rail that
 *  is translating 1:1 with the scroll moves a whole step between samples, so
 *  two consecutive samples cannot both land inside this band by accident. */
const PIN_TOLERANCE = 2;
/** The walk's stride, in scrolled pixels. Small enough that the shortest real
 *  plateau (387px of runway) is sampled a dozen times, large enough that the
 *  whole spine is walked in one test. */
const PIN_STEP = 24;
/** How far outside the pin the walk starts and ends, so the approach and the
 *  exit — the two stretches where a working rail DOES translate 1:1 — are in
 *  every reading. It is what makes "the rail entered and left" assertable. */
const PIN_LEAD = 120;
/**
 * The least share of its own band a rail may spend pinned — counting only the
 * pin the BAND pays for (`pinned - overhang`, see `RailWalk.overhang`).
 *
 * MEASURED on `next build && next start` (2026-08-20, the FLUID-SPREAD
 * restaging: the descent's rails scale 30→40rem / 36→44rem with viewport
 * width from a frozen 1024 base, and the container widened to 85rem —
 * `ClaimsDescent`'s sizing docblock derives it; the 1024 rows below are
 * unchanged from the prior table because 1024 is the ramp's floor by
 * construction), verdict / rules / review / row / retention, at each of the
 * six viewports this walk runs — taken with the design-side walk (same band
 * arithmetic, stable-top plateau at tolerance 2 / step 24, overhang netted,
 * which is inert on this page anyway); this suite's own run is owed and is
 * the canonical reading:
 *
 *   1024x600    0.570  0.354  0.371  0.314  0.742
 *   1024x768    0.547  0.469  0.335  0.357  0.768
 *   1512x600    0.583  0.312  0.371  0.314  0.725
 *   1512x949    0.531  0.524  0.325  0.415  0.764
 *   1512x1080   0.533  0.571  0.333  0.492  0.784
 *   1024x1120   0.525  0.643  0.321  0.566  0.812
 *
 * RE-RECORDED 2026-08-21 from the suite's own canonical run. The ROW
 * column moved by -0.172 to -0.290 and nothing else moved at all (four
 * columns identical to 0.000; retention at 1024x600 is -0.014, about 21px
 * of `pinned`, inside one 24px PIN_STEP — stride granularity, not drift).
 * The cause is known and intended: that rail's clip was re-captured at 4:3
 * (1408x1056) to become the big left-hand box, so the exhibit grew taller
 * and ate its own runway.
 *
 * Reading the minimum FROM the table, nothing else: RULES 0.312 at
 * 1512x600, then ROW 0.314 at two corners, then review 0.321 at 1024x1120.
 * The rules rail's short edge is 0.312 because the fluid width grows that
 * exhibit ~57px at the wide-short corner (height-capped, so its transport
 * keeps the fold) while its band barely moves. The row rail arrives second
 * for the recapture reason above, and it did not appear in this sentence
 * at all until the canonical run put it there. A
 * caution that is now part of this table's method: this prose has named
 * the wrong corner FOUR times now. The fourth: after the 4:3 recapture the
 * design-side walk reported "row 0.314/0.415, others within 0.02" and did
 * not re-record the table, so this prose kept naming review as the minimum
 * while a whole column sat stale by up to 0.290 and the true argmin had
 * already moved to rules. The lesson is not "measure more carefully", it
 * is that a summary sentence and the table under it drift apart the moment
 * one is updated without the other. So
 * the sentence above is derived from the table each time the table is
 * re-measured, never carried forward, and the corner it names is a summary
 * of THIS table, not a fact about the page. The floor keeps more clearance
 * than the old spine's tightest corner and is deliberately NOT raised to
 * suit, because the number it has to survive is the next restaging's, not
 * this one's.
 *
 * The paragraphs below this line predate the five-rail restaging: their
 * numbers describe the three-rail spine and the retired `#access` rail, and
 * are kept as the record of how this floor was set — the mechanisms they
 * name (mb-14's price, the corner blind spots, the band-vs-runway
 * denominator) are unchanged.
 *
 * Beyond-range probes, because the two viewport-tall rails converge on an
 * asymptote rather than a cliff: decision reads 0.329 at 1920x1200 and
 * 0.321 at 2560x1440 (its band is ~1.4·dvh once both paced claims bind, so
 * the share tends to (1.4-1)/1.4 ≈ 0.29 and never crosses the floor).
 *
 * THE TIGHTEST READING IS #ACCESS AT 1512x600 — WIDE AND SHORT — at 0.213.
 * The revision before this one named 1024x600's 0.236 and said 0.20 "sits 15%
 * below the tightest of the twelve readings". That was false, and false in
 * this file's characteristic way: 0.236 was the tightest reading the walk
 * TOOK, not the tightest the page HAS. A sweep of 21 viewports puts the
 * minimum at 0.213, at height 600 and every width from 1100 up — measured
 * identically to three decimals at 1100, 1279, 1280, 1440, 1512 and 1920.
 * Widening from 1024 wraps #access's prose shorter and drops its band 812 ->
 * 788 while the rail grows 553 -> 557, so the pin loses at both ends.
 *
 * DECOMPOSED at 1512x600, because which ratio you name changes what the
 * number means:
 *
 *   (band - rail)/band   231/788 = 0.293   what the flow column supplies
 *   runway/band          175/788 = 0.222   after `mb-14` spends 56px landing
 *                                          the exhibit on the closing line
 *   share, i.e. the gate 168/788 = 0.213   after PIN_STEP granularity
 *
 * So the structural headroom over the floor is 2.2pp — 0.222 against 0.200 —
 * and what the gate actually reads clears it by 1.3pp, 6.5% of the floor. Not
 * 15% of anything, and not the 44% this floor was first set with. Between
 * 1100 and 1279 the same 0.213 arrives by a different route: the exhibit is
 * 4px shorter below `xl`, so runway/band is 179/788 = 0.227 there and the
 * stride eats the extra. Same gate reading, so that stretch needs no walk of
 * its own.
 *
 * `mb-14` COSTS 7.1pp OF THAT SHARE — 56px of a 788px band, three times the
 * margin that is left over. It is a deliberate trade for the level close (the
 * exhibit comes to rest on the phase's closing line, where the flow column's
 * last beat ends too — `ClaimsDescent`), and it is written down here because
 * its price never had been. If this floor is ever genuinely in the way, that
 * margin is the term to argue about before the floor is.
 *
 * NOTHING INSIDE THE DESIGN RANGE (w >= 1024, h >= 600) IS UNDER THE FLOOR.
 * Outside it the page does read red, and the crossing sits between 580 and
 * 600px tall at 1100+ wide: #access reads 0.187 at 1152x580 and 0.190 at
 * 1152x560, while 1024x560 is still 0.215. That is where the contract ends,
 * not a defect — 600 is the shortest viewport this page is designed for.
 *
 * WHY THIS LIST OF VIEWPORTS, since it has now been wrong THREE times in
 * the same shape. Each time the set was chosen AFTER the measurement that
 * justified it, so the measurement could not see its own blind spot.
 * dc1bdee walked 1024x768 alone, claimed 24% of headroom, and was NEGATIVE
 * at 1512x949; a47d8e0 walked three viewports across two widths, claimed
 * 15%, and read 0.213 at 1512x600, which was not one of them; and the take
 * rework (b140562) walked four corners topping out at 949 while its own
 * new staging — a viewport-tall rail over a content-paced band — collapsed
 * linearly with HEIGHT: 0.305 at 949, 0.191 at 1512x1080, 0.110 at
 * 2560x1440. The blind spot went tall→wide→tall again: always one corner
 * past the set.
 *
 * So the list is not a sample of the range, it is the CORNERS of it —
 * {1024, 1512} x {600, 768/949, 1080/1120}, the short edge, the working
 * middle and the TALL edge — because width and height squeeze a rail by
 * different mechanisms and neither predicts the other: a narrower column
 * wraps the prose longer and lengthens the band, `xl:pt-1` on the caption
 * grows the exhibit past 1280, a short viewport floors the sticky offset at
 * `5rem`, and a viewport-tall rail grows 1:1 with dvh so height is a squeeze
 * all of its own. A minimum built from independent mechanisms lives at a
 * corner, not along an edge; dropping a corner is what has now gone wrong
 * three times, and the tall pair exists so nobody repeats the third.
 *
 * The netting is currently INERT and deliberately kept. No rail on this page
 * carries a negative bottom margin any more (the clip rails carry `mb-14`,
 * positive), so `overhang` is 0 in every reading above and nets nothing. It
 * exists because the staging that did carry one measured, un-netted, on a
 * band collapsed to its rail's own height: 0.174 at 1024x768, 0.200 at
 * 1280x800, 0.249 at 1512x949, 0.288 at 1728x1080 — i.e. a rail with NO
 * runway sailing past this floor on nothing but its own margin, at every
 * viewport from 1280x800 up. A term that costs one subtraction and closes
 * that stays.
 *
 * The denominator is the BAND, not the runway: pin/runway is ~0.97 on the
 * fixed page and would be ~1.00 on the broken one (a 1px runway is 1px
 * "pinned"), so measuring against the runway is precisely the check that
 * cannot fail.
 */
const MIN_PIN_SHARE = 0.2;

/** One rail's traversal, as measured by `walkRails`. */
type RailWalk = {
  label: string;
  offset: number;
  bandHeight: number;
  railHeight: number;
  /** How far the rail's border box may pass its band's end, i.e. the negative
   *  bottom margin the three clip rails carry to take their centring slack
   *  back (`ClaimsDescent`). It is pin the MARGIN pays for rather than the
   *  band, so the walk has to reach past it and the share has to net it off. */
  overhang: number;
  runway: number;
  pinned: number;
  approach: number;
  exit: number;
  trace: string;
};

/**
 * Scroll each pinned rail through its own band and report how far it held at
 * its sticky offset.
 *
 * THE BAND IS THE RAIL'S PARENT, and that is not a convenience: `position:
 * sticky` travels inside its containing block, so the parent's box IS the
 * runway. Reading it from the DOM rather than from a section selector means a
 * phase restaged into a different wrapper is still measured.
 *
 * The runway is `bandHeight - railHeight` LESS the rail's bottom margin,
 * signed, because what sticky keeps inside the band is the MARGIN box. The
 * three clip rails carry `mb-14` so their exhibit comes to rest on the
 * phase's closing line (`ClaimsDescent`), which ends the pin 56px early; an
 * earlier staging carried a NEGATIVE margin instead, which ended it late, and
 * the border-box arithmetic then stopped the walk 192px INSIDE the sync
 * rail's pin, read `exit` at the sticky offset, and reddened "it never left
 * its band" on a page that was working. Subtracting the signed margin is
 * right for either sign and inert at zero, which is what the verdict rail and
 * every rail before this staging read. Nothing else here moves.
 *
 * `pinned` counts only the scroll distance between two CONSECUTIVE samples
 * that both read the offset. A single sample at the offset earns nothing —
 * every rail passes through 80 on its way past, and the pre-fix defect passed
 * through it too.
 *
 * The walk runs in one `page.evaluate` with a rAF between scrolls rather than
 * as a Playwright scroll loop: the sticky position is layout, not script, so a
 * frame is all it needs, and ~130 samples across the spine's rails would be
 * ~130 round trips.
 */
async function walkRails(page: Page): Promise<RailWalk[]> {
  return page.evaluate(
    async ({ sel, step, lead, tolerance }) => {
      const frame = () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        );
      const rails = Array.from(document.querySelectorAll<HTMLElement>(sel));
      const walks = [];

      for (let index = 0; index < rails.length; index += 1) {
        const rail = rails[index];
        const band = rail.parentElement;
        if (!band) throw new Error(`rail ${index} has no containing block to pin inside`);

        // Named by where a reader would look for it: the section's own id or
        // label, plus the exhibit it carries. The three descent rails share one
        // unnamed <section>, and two of them carry the same chrome strip, so
        // the recording's own name (`ProductClip` puts it on the <video>) is
        // what tells them apart in a failure message.
        const section = rail.closest("section");
        const where = section?.id
          ? `#${section.id}`
          : (section?.getAttribute("aria-label") ?? "an unnamed section");
        const carried =
          rail.querySelector("video[aria-label]")?.getAttribute("aria-label") ??
          rail.querySelector(".label-caps, figcaption, p")?.textContent?.trim();
        const named = rail.dataset.rail ? `the ${rail.dataset.rail} rail` : `rail ${index}`;
        const label = `${named} in ${where}${carried ? ` (${carried.slice(0, 32)})` : ""}`;

        // Park at the approach BEFORE measuring. The descent drives its
        // exhibits off scroll progress, so a band's height read from the top
        // of the document can be stale by the time the walk reaches it.
        const rough = window.scrollY + band.getBoundingClientRect().top;
        window.scrollTo({ top: Math.max(0, rough - lead), behavior: "instant" });
        await frame();

        // The offset is the browser's reading of the rail's own `top-20`, not
        // a number restated here — and so is the overhang, off the same
        // computed style, so a rail that stops reclaiming its slack is
        // measured as it renders rather than as this file remembers it.
        const railStyle = getComputedStyle(rail);
        const offset = parseFloat(railStyle.top);
        const margin = parseFloat(railStyle.marginBottom);
        const overhang = Math.max(0, -margin);
        const bandRect = band.getBoundingClientRect();
        const bandTop = window.scrollY + bandRect.top;
        const bandHeight = bandRect.height;
        const railHeight = rail.getBoundingClientRect().height;
        const runway = bandHeight - railHeight - margin;

        const from = bandTop - offset - lead;
        const to = bandTop + runway - offset + lead;
        const samples: { y: number; top: number }[] = [];
        for (let y = from; y <= to + 0.5; y += step) {
          window.scrollTo({ top: Math.max(0, Math.round(y)), behavior: "instant" });
          await frame();
          samples.push({
            y: window.scrollY,
            top: Math.round(rail.getBoundingClientRect().top * 10) / 10,
          });
        }

        const held = (s: { top: number }) => Math.abs(s.top - offset) <= tolerance;
        let pinned = 0;
        for (let i = 1; i < samples.length; i += 1) {
          if (held(samples[i - 1]) && held(samples[i])) pinned += samples[i].y - samples[i - 1].y;
        }

        // A readable slice of the walk for the failure message — the pre-fix
        // signature is a top that falls by a whole step at every sample.
        const every = Math.max(1, Math.ceil(samples.length / 10));
        walks.push({
          label,
          offset,
          overhang: Math.round(overhang),
          bandHeight: Math.round(bandHeight),
          railHeight: Math.round(railHeight),
          runway: Math.round(runway),
          pinned: Math.round(pinned),
          approach: samples.length ? samples[0].top : Number.NaN,
          exit: samples.length ? samples[samples.length - 1].top : Number.NaN,
          trace: samples
            .filter((_, i) => i % every === 0)
            .map((s) => s.top)
            .join(" "),
        });
      }

      return walks;
    },
    { sel: STICKY_EXHIBIT, step: PIN_STEP, lead: PIN_LEAD, tolerance: PIN_TOLERANCE },
  );
}

/**
 * Scroll so a run of COPY sits at the viewport's midpoint, which is where the
 * descent's own boundary lives. Derived from the element, so it survives any
 * change to the claims' heights — and addressed by the words the reader sees
 * rather than by a hook, because the sentinels the observers needed are gone
 * and a test-only attribute would be a knob rather than a measurement.
 */
async function centreOnText(page: Page, text: RegExp): Promise<void> {
  const target = page.getByText(text).first();
  await expect(target).toBeAttached();
  await target.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const midpoint = window.scrollY + rect.top + rect.height / 2;
    window.scrollTo({ top: Math.max(0, midpoint - window.innerHeight / 2), behavior: "instant" });
  });
  await page.waitForTimeout(150);
}

async function settledHeight(page: Page, selector: string): Promise<number> {
  const read = () =>
    page.evaluate(
      (sel) => document.querySelector(sel)?.getBoundingClientRect().height ?? -1,
      selector,
    );
  await page.waitForTimeout(600);
  let previous = await read();
  for (let i = 0; i < 40; i += 1) {
    await page.waitForTimeout(100);
    const current = await read();
    if (current > 0 && current === previous) return current;
    previous = current;
  }
  throw new Error(`${selector} never settled (last height ${previous})`);
}

/**
 * The closing sequence's playhead, in seconds. `ClosingAct` writes `--act-t`
 * on the band from its own slowed clock once the scene is in view, and
 * globals.css freezes every animation at that time — so this one number is
 * the whole state of the scene: 0 before it has been seen, ACT_SECONDS once
 * the play has genuinely finished, anything between mid-play.
 */
async function playhead(page: Page): Promise<number> {
  return page.evaluate(() => {
    const band = document.querySelector(".act-band");
    if (!band) return -1;
    return parseFloat(getComputedStyle(band).getPropertyValue("--act-t")) || 0;
  });
}


/**
 * The window act's own surfaces, scoped and EXACT — the lesson of this
 * file's first red run (2026-08-20): `getByRole(…, { name })` is
 * case-insensitive SUBSTRING matching by default, so an unscoped
 * `{ name: "Play" }` resolved to SIX buttons — the act's Play, its own
 * Replay (contains "play"), the ProductClip transports and the closing
 * act's "Replay the closing sequence" — and the strict-mode violation meant
 * the take trio's real assertions never executed. Every locator here is
 * scoped to the act's section and matched exactly, so a transport joining
 * another surface (a clip autoplaying, a second Replay) can never make
 * these ambiguous again.
 */
function theAct(page: Page) {
  const section = page.locator("section[aria-label='The board, live']");
  return {
    section,
    strip: section.locator("p[aria-live='polite']"),
    pause: section.getByRole("button", { name: ACT.pause, exact: true }),
    play: section.getByRole("button", { name: ACT.play, exact: true }),
    replay: section.getByRole("button", { name: ACT.replay, exact: true }),
    /** The synthesized pointer's SVG path — nothing else draws this shape. */
    pointer: section.locator("svg path[d^='M3 1']"),
  };
}

/**
 * A rail take's own surfaces, scoped the same way `theAct`'s are and for the
 * same recorded reason — and for a second one this file has now paid for
 * twice: the provenance test addressed the verdict exhibit's wall label as
 * `.locator("p").first()`, and when `RailTake` put two new `<p>` elements
 * ahead of the exhibit (the caps strip, the aria-live narration) the locator
 * silently resolved to the strip and the containment assertions below it
 * never executed. Every handle here is the element's ROLE or its own
 * attribute, matched exactly, so an element added ahead of it cannot
 * re-ambiguate it: the strip is the rail's one `aria-live` line, and the
 * transport is addressed by its exact accessible name.
 */
function theRailTake(page: Page, rail: "verdict" | "review") {
  const self = page.locator(`[data-rail='${rail}']`);
  return {
    self,
    strip: self.locator("p[aria-live='polite']"),
    pause: self.getByRole("button", { name: ACT.pause, exact: true }),
    play: self.getByRole("button", { name: ACT.play, exact: true }),
    replay: self.getByRole("button", { name: ACT.replay, exact: true }),
  };
}

/**
 * The descent exhibit's two live verdicts, addressed by the product's OWN
 * attributes (`data-verdict-chip`, `data-verdict-chips`, added to
 * `VerdictEmail` for this gate). A loose locator has sat here twice and cost
 * the fold test the same block both times — `.locator("p").first()`, then
 * `getByText("whole body")`. The second is substring matching, and the
 * beat's narration quotes the chip verbatim ("the preview alone looks
 * routine — the whole body holds the invitation"), so at the split beat it
 * resolves 2 nodes inside the rail: strict-mode violation, and `expect`
 * fails fast, so the containment assertions below it never ran.
 *
 * `exact: true` is not the fix, and the reason is worth stating because it
 * looks like one. MEASURED at the split beat, production build (2026-08-20):
 * inside the rail it resolves 1, but page-wide it resolves 6 — the other
 * mounts of the same exhibit — so it is scope, not exactness, doing the
 * work, and what is left is a locator that stays unique only while the chip
 * is its own element and no beat is reworded to END on that phrase. Both
 * prior breaks were exactly that kind of contingency coming due. An
 * attribute is an address: an element added ahead of it, a restyle, or a
 * rewritten script cannot re-ambiguate it.
 *
 * `box` is the element the collapse ZEROES — `grid-rows-[0fr]` on its grid
 * parent, and Playwright's visibility check is a non-empty box — so `box` is
 * the only handle here that can actually read "the verdicts are open". A
 * chip cannot, and that was MEASURED rather than assumed: on the page's own
 * collapsed mount of this exhibit (the record at rest, same production
 * build) the chips box read 414x0 and INVISIBLE while the chip inside it
 * read VISIBLE with a 187x97.9 box — the clip is an ancestor's
 * `overflow-hidden`, which Playwright's visibility check does not resolve.
 * So the chips are asserted by COUNT; a `toBeVisible` on a chip would be one
 * more check that cannot fail.
 */
function theVerdictChips(scope: Locator) {
  return {
    box: scope.locator("[data-verdict-chips]"),
    preview: scope.locator("[data-verdict-chip='preview only']"),
    body: scope.locator("[data-verdict-chip='whole body']"),
  };
}

test.describe("landing (/)", () => {
  test.skip(
    !PROD_BUILD,
    "Runs only against `next start`; set PLAYWRIGHT_PROD_BUILD=1. `next dev` has produced false reds on this page's geometry.",
  );

  test("the four acts render at 1024, with a clean console", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    // 1 — the promise.
    await expect(
      page.getByRole("heading", { name: /You lose the email/i }),
    ).toBeVisible();
    // 2 — the window, with the REAL board mounted in it (not the skeleton).
    await expect(page.locator("section[aria-label='The board, live']")).toBeVisible();
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    // 3 — the descent, and the spine's pinned rails: one per phase, no phase
    // out of the language.
    await expect(
      page.getByRole("heading", { name: /The preview ends before the verdict/i }),
    ).toBeVisible();
    // A COUNT, and only a count: `div.sticky.top-20` says the class is
    // declared, never that the rail travels. That difference shipped a defect
    // (see the pin test below, which is the assertion this line cannot make).
    await expect(page.locator(STICKY_EXHIBIT)).toHaveCount(RAIL_COUNT);
    // 4 — the conversion surface and the closing act.
    await expect(page.getByRole("heading", { name: /One hundred seats/i })).toBeVisible();
    await expect(page.locator("section.act")).toHaveCount(1);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  /**
   * THE TAKE TRIO — the workday oner's own gates, replacing the scrubbed
   * act's suite (see the header). All three were WRITTEN BLIND, in a session
   * that could not run Playwright; all three have since been watched red and
   * green, each mutation on its own `next build && next start` (2026-08-20).
   * Every strip assertion and every count carries the mutation that reddens
   * IT; the transport-visibility lines that follow one of those are
   * evaluated but never watched red, and are named as such below rather
   * than counted as coverage. The blind period is recorded and not erased:
   * the
   * first recipe written for the reduced-motion counts was never run, and
   * when it finally was it passed — see the note there.
   *
   * The narration line is addressed by copy (`ACT.narration`, imported), so
   * a retimed script cannot silently detach these from the words the reader
   * sees. The take starts on its own once the frame is ≥35% in view — at the
   * top of the page that is load — and its first beat waits for the board's
   * dynamic chunk, so the polls here are generous rather than tight.
   */
  test("the take plays itself: the narration advances and the transport appears", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    // The board is the take's own precondition (`waitFor` inside the script).
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    // The opening line gives way to the first narrated beat.
    const act = theAct(page);
    // MUTATION (watched red 2026-08-20, first run): ACT.narration[0] deleted
    // from the script — the take played its other six beats in order and
    // this line simply never appeared. It isolates THIS assertion only.
    await expect(act.strip).toHaveText(ACT.narration[0], { timeout: 20_000 });
    // A >5s autoplaying surface owes its viewer a pause (WCAG 2.2.2), in the
    // frame's own chrome. NAMED, NOT CLAIMED: `expect` fails fast, so this
    // line never executes under the mutation above. It has been seen green
    // and has no isolating mutation of its own.
    await expect(act.pause).toBeVisible();
  });

  /**
   * EVERY PRESS LANDS FRAMED — the recut's one camera covenant, and the
   * invariant all three of the owner's complaints about the zoomed cut
   * violated (2026-08-21): the camera cropped the momentum panel and then
   * clicked inside it; it framed near the deadlines cell while nothing was
   * pressed there; and it pressed a worklist row while still framed on the
   * pulse. The zoom-era gates (shot depth, travel range, the cover-floor
   * void watcher) retired WITH the zoom — a scale-locked camera cannot
   * travel in scale, so a range assertion would gate a contract that no
   * longer exists — and this is what replaced them: at the instant of every
   * synthesized press, the pressed element's bounding rect must sit whole
   * inside the frame's rect. The camera frames the press BEFORE the pointer
   * lands it, or this reds with the control's own name and how far outside
   * the frame it was.
   *
   * MEASURED FROM OUTSIDE the code under test: an init-script capture
   * listener records every `isTrusted: false` pointerdown inside the frame
   * (only the take's pointer dispatches those there) and takes its own
   * rects. The positive control is the count — the script presses four
   * controls (the momentum cell, the day bar, Kestrel's row, the filter's
   * clear), so fewer than four recorded presses means the listener measured
   * nothing and its zero violations are not evidence.
   *
   * 1024x600 DELIBERATELY: the shortest supported frame is the only corner
   * where the camera must actually pan to keep this true (at 1024x1120 the
   * whole board sits inside the frame at natural size and the invariant is
   * unbreakable by construction). 1px of slack is rect rounding.
   *
   * MUTATION (watched red 2026-08-21 via the design-side twin of this exact
   * listener — same bundle, same browser, same arithmetic; this suite's own
   * run is owed and canonical): a press of the worklist's LAST row inserted
   * before the take's first beat, with no pan before it — at 600 tall that
   * row is far below the frame's foot. The take completed, the last
   * narration line still landed, and the press recorded as "Open Atlas
   * Freight — Software Engineer II" at gap +328.4px while all four scripted
   * presses stayed negative — this gate reds alone. Restored and watched
   * green the same way (gaps -20 / -153 / -38 / -31 at 1024x600).
   */
  /**
   * BOTH VIEWPORTS, because the exempt one is not the one that matters.
   * The gate ran at 1024x600 alone for a commit. At 1024x1120 the whole
   * board fits and the camera provably never pans, so containment there is
   * structural rather than earned — but 1512x949, the owner's own screen,
   * is neither exempt nor was it gated, and the camera demonstrably travels
   * there. Canonical gaps: -20 / -153 / -38 / -31 at 1024x600, and
   * -20 / -191 / -230 / -124.5 at 1512x949.
   *
   * AND THE 1512 INSTANCE IS THE WEAK ONE, said plainly rather than left
   * for someone to discover. The mutation that reds 1024x600 at +328.4px —
   * an unpanned press of the worklist's last row — was measured GREEN at
   * 1512x949, reading gap -20.6: at that viewport the row is inside the
   * frame whether the camera pans to it or not. A second variant, the same
   * press moved behind the detail-pane beat, passed at both viewports for
   * a different reason: by then the board is filtered to three rows and
   * "last row" resolves to a row already framed.
   *
   * So this instance currently has ~20px of margin and no mutation that
   * reds it. It is NOT vacuous the way 1024x1120's pan clause was — the
   * margin is finite and the camera really does travel 1.8px — but the
   * reason it holds is close to structural: a scale-locked camera plus a
   * board that fits the frame leaves little for a mis-framed press to fall
   * off. That is also why the owner's original defect could not reproduce
   * here after the recut: it needed a ZOOMED frame showing a fraction of
   * the board, which no longer exists.
   *
   * It is kept because it stops being structural the moment the
   * composition grows the board past the frame at this width, which is
   * live work (see the resolution-matrix issue). If a future reader finds
   * this instance still unfailable and the composition unchanged, deleting
   * it is defensible; what is not defensible is leaving it here while
   * believing it guards something.
   */
  for (const [pressLabel, pressViewport] of [
    ["1024x600", DESKTOP_1024],
    ["1512x949", DESKTOP_1512],
  ] as const) {
    test(`every press lands inside the frame at ${pressLabel}: the camera frames what the pointer clicks`, async ({
      page,
    }) => {
      await page.setViewportSize(pressViewport);
      await page.addInitScript(() => {
        interface Press {
          label: string;
          gap: number;
        }
        const presses: Press[] = [];
        (window as unknown as { __presses: Press[] }).__presses = presses;
        document.addEventListener(
          "pointerdown",
          (event) => {
            // The visitor's hand is trusted; the take's pointer is not. Only
            // the synthesized presses are this gate's subject.
            if (event.isTrusted) return;
            const el = event.target instanceof HTMLElement ? event.target : null;
            const frame = document.querySelector<HTMLElement>("[data-cam-scale]");
            if (!el || !frame || !frame.contains(el)) return;
            const r = el.getBoundingClientRect();
            const f = frame.getBoundingClientRect();
            const gap = Math.max(
              f.left - r.left,
              r.right - f.right,
              f.top - r.top,
              r.bottom - f.bottom,
            );
            presses.push({
              label: el.getAttribute("aria-label") ?? (el.textContent ?? "").slice(0, 40),
              gap: Math.round(gap * 10) / 10,
            });
          },
          true,
        );
      });
      await page.goto("/");
      await expect(page.getByTestId("pipeline-board")).toBeVisible();

      // The whole take, at authored tempo: the last narration line is the
      // script's own "done", and every press has happened by the time it shows.
      const act = theAct(page);
      await expect(act.strip).toHaveText(ACT.narration[6], { timeout: 45_000 });

      const presses = await page.evaluate(
        () => (window as unknown as { __presses: { label: string; gap: number }[] }).__presses,
      );
      expect(
        presses.length,
        `only ${presses.length} synthesized press(es) were recorded — the listener measured little or nothing, so zero violations is not evidence`,
      ).toBeGreaterThanOrEqual(4);
      for (const press of presses) {
        expect(
          press.gap,
          `"${press.label}" was pressed ${press.gap}px outside the frame — the camera did not frame the press before the pointer landed it`,
        ).toBeLessThanOrEqual(1);
      }
    });
  }

  /**
   * THE CAMERA IS SEEDED AND IT NEVER CUTS. Two of the three clauses the
   * zoomed cut needed, kept because they still mean something at scale 1:
   *
   *   1. SEEDED — the director exists from mount (layout effect) and writes
   *      its resting transform before first paint, so no frame ever renders
   *      the camera untransformed. (The historical defect: ~500ms of bare
   *      board, then a hard snap when the take's first write landed.)
   *   2. CONTINUOUS — every stage change the take does not author (the day
   *      filter's collapse, the pane's mount, the clear beat's regrowth,
   *      the skeleton handoff) is absorbed by the reframe as an eased move
   *      (`director.ts`). The assertion is a per-frame DISPLACEMENT limit
   *      on the rendered camera — how far it moved between two adjacent
   *      rendered frames, full stop, no division by dt (a dt-normalised
   *      rate was measured false-redding on rAF tick bunching at 1512x949:
   *      an ordinary eased frame over a 1.4ms divisor read 24.29 scale/s
   *      against a bound of 6; displacement is dt-free and the mechanism
   *      cannot recur). The historical cut this guards against was a 447px
   *      pan snap between two frames 8ms apart.
   *
   * THE BRACED CLAUSE RETIRED 2026-08-21 with the zoom recut, and its
   * assertion (with its collapse positive-control) came out rather than
   * being kept green-forever: the brace existed to carry a ZOOMED camera
   * across the day filter's single-pass collapse, and a camera locked at
   * scale 1 has no cover scale to arrive at — the contract it gated no
   * longer exists. Its mutation evidence lives in git history with the
   * machinery (`Director.brace`, `filteredCover`, `COVER_MAX`).
   *
   * THE SCALE BOUND IS ZERO, and the zoom-era ceilings (0.18 / 0.115) are
   * gone. They were kept for one commit on the reasoning that a
   * scale-locked camera sits 100% under them, which was true and useless:
   * canonical measurement reads scale displacement of exactly 0.0000 at
   * both viewports, so a ceiling of 0.18 would have let a returning zoom
   * of up to 0.18 per frame through in silence. The docblock claimed "any
   * reading above 0.0 at all now means a zoom came back" while the
   * assertion said otherwise; the assertion was wrong, and this is what
   * that sentence always meant. `data-cam-scale` is the constant 1.000 by
   * contract, so the honest assertion is equality.
   *
   * THE PAN BOUND IS NOW TWO ASSERTIONS, because a single ceiling went
   * vacuous at one corner. At 1024x1120 the whole board fits the frame and
   * the minimal-move camera correctly never stirs: canonical reads
   * maxPanStep of exactly 0.0 over 1970 frames, so `<= 100` was comparing
   * zero against a hundred — a check that cannot fail, introduced by the
   * recut itself. That corner now asserts the property it actually has
   * (the camera does not move at all), and 1512x949, where the camera
   * demonstrably does pan, asserts BOTH that it moved and that it never
   * jumped. `pans` in the tuple is which contract the shot is under.
   * Canonical pan at 1512x949 is 1.8px, dead stable across six repeats,
   * not the 1.9-to-4.1 spread an earlier draft of this block recorded:
   * the 4.1 came from a run carrying a press mutation that changes the
   * take, and comparing it against a clean run was a measurement error.
   *
   * MUTATION EVIDENCE, all three watched red 2026-08-21 on their own
   * production builds, each verified by reading the shipped `applyCam` in
   * the chunk rather than by hashing `.next/static` (BUILD_ID sits in that
   * path, so the aggregate hash changes on byte-identical sources and
   * discriminates nothing):
   *   · SCALE: a returning zoom of 0.002 amplitude reds both viewports at
   *     0.0040 — 45x below the retired 0.18 ceiling, which is exactly the
   *     regression the old bound admitted in silence.
   *   · STIR: a 0.5px sine on the camera reds 1024x1120 alone at 0.9px,
   *     and would have sailed under the old `<= 100`.
   *   · FREEZE: pinning the transform reds 1512x949 alone on the "never
   *     panned" line.
   * The last two red in exactly one viewport each, which is the evidence
   * that the per-viewport split does real work rather than being decor.
   *
   * AND THE WATCHER HAS A POSITIVE CONTROL AT LAST. Mutating its
   * camera-finding predicate so it could never locate the element was
   * measured GREEN on all three assertions across 1972 samples: `unseeded`
   * is false when `camera` is null, and the displacement loop `continue`s
   * on a null scale, so a watcher that measured nothing passed. That hole
   * predates the recut and is the same one closed in the void watcher.
   * `located` is the fix, and it is a RATIO for the reason recorded there:
   * a bare frame count floors the runner's frame rate, which has nothing
   * to do with the defect.
   *
   * TWO VIEWPORTS, unchanged reasoning: every camera number is a function
   * of the frame's dimensions, and the fluid composition widens the frame
   * by up to ~208px above 1280 — 1512x949 measures the camera on a width
   * where 1024 contributes nothing.
   */
  for (const [label, viewport, pans] of [
    ["1024x1120", DESKTOP_1024_TALL, false],
    ["1512x949", DESKTOP_1512, true],
  ] as const) {
    test(`the camera is seeded and continuous at ${label}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      // The watcher must predate the board: the unseeded-camera defect lives
      // in the window between the camera mounting and the take's first move.
      await page.addInitScript(() => {
        interface CamSample {
          t: number;
          unseeded: boolean;
          s: number | null;
          x: number | null;
          y: number | null;
          sh: number | null;
          fh: number | null;
        }
        const samples: CamSample[] = [];
        (window as unknown as { __cam: CamSample[] }).__cam = samples;
        // The camera is found STRUCTURALLY — walk up from the board to the
        // element carrying a transform-origin — never via `[data-cam-scale]`:
        // the dataset is written by the code under test, so a camera that was
        // never composed would also never be found, and the unseeded count
        // could not fail. (The first cut of this watcher had exactly that
        // hole a second way: it compared `style.transformOrigin === "0 0"`,
        // which the CSSOM serializes as `0px 0px`, so the predicate matched
        // nothing and the seed mutation stayed green. Watched, then fixed.)
        const tick = () => {
          const board = document.querySelector<HTMLElement>('[data-testid="pipeline-board"]');
          let camera: HTMLElement | null = null;
          for (let el = board?.parentElement ?? null; el; el = el.parentElement) {
            if (el instanceof HTMLElement && el.style.transformOrigin) {
              camera = el;
              break;
            }
          }
          const frame = camera?.parentElement ?? null;
          samples.push({
            t: performance.now(),
            unseeded: !!camera && !camera.style.transform,
            s: frame?.dataset.camScale ? Number(frame.dataset.camScale) : null,
            x: frame?.dataset.camX ? Number(frame.dataset.camX) : null,
            y: frame?.dataset.camY ? Number(frame.dataset.camY) : null,
            sh: camera?.firstElementChild instanceof HTMLElement ? camera.firstElementChild.offsetHeight : null,
            fh: frame ? frame.getBoundingClientRect().height : null,
          });
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
      await page.goto("/");
      await expect(page.getByTestId("pipeline-board")).toBeVisible();
      // Long enough to cover the establishing handoff, the filter beat and
      // the pane mount at authored tempo (collapse ~7.3s, mount ~11.5s).
      await page.waitForTimeout(16_000);
      const samples = await page.evaluate(
        () =>
          (window as unknown as { __cam: { t: number; unseeded: boolean; s: number | null; x: number | null; y: number | null; sh: number | null; fh: number | null }[] }).__cam,
      );

      // 1 — SEEDED: no frame ever renders the camera untransformed.
      // The watcher's own positive control, before anything it measured is
      // trusted. See the docblock: a blind watcher passed all three.
      const located = samples.filter((r) => r.s !== null).length;
      expect(
        located,
        `the watcher located the camera on ${located} of ${samples.length} sample(s) — it measured nothing, so its zeroes are not evidence`,
      ).toBeGreaterThan(samples.length * 0.8);

      const unseeded = samples.filter((r) => r.unseeded).length;
      expect(
        unseeded,
        `${unseeded} frame(s) rendered with the camera untransformed — the establishing shot is being cut to, not seeded (Director's constructor seed)`,
      ).toBe(0);

      // 2 — CONTINUOUS: how far the rendered camera moves between two
      // adjacent frames. Displacement, not a rate — see the docblock for
      // why dividing by dt was the defect and not the measurement.
      let maxScaleStep = 0;
      let maxPanStep = 0;
      for (let i = 1; i < samples.length; i++) {
        const a = samples[i - 1]!;
        const b = samples[i]!;
        if (a.s === null || b.s === null || Number.isNaN(a.s) || Number.isNaN(b.s)) continue;
        if (b.t <= a.t) continue;
        maxScaleStep = Math.max(maxScaleStep, Math.abs(b.s - a.s));
        maxPanStep = Math.max(maxPanStep, Math.abs(b.x! - a.x!), Math.abs(b.y! - a.y!));
      }
      expect(
        maxScaleStep,
        `the camera's scale moved ${maxScaleStep.toFixed(4)} — the oner is scale-locked at 1.000, so any movement at all is a zoom coming back`,
      ).toBe(0);
      if (pans) {
        // The camera demonstrably travels here, so both halves are real: it
        // moved, and it never jumped. Canonical readings run 1.9 to 4.1px.
        expect(
          maxPanStep,
          `the camera never panned at this viewport — the pan bound below has nothing to measure, so its pass is not evidence`,
        ).toBeGreaterThan(0);
        expect(
          maxPanStep,
          `the camera jumped ${maxPanStep.toFixed(0)}px between two frames — a cut, not a move (reframe's absorb)`,
        ).toBeLessThanOrEqual(100);
      } else {
        // The board fits the frame here, so the minimal-move camera should
        // never stir. Asserting the property it HAS beats a ceiling it sits
        // infinitely far under.
        expect(
          maxPanStep,
          `the camera panned ${maxPanStep.toFixed(1)}px at a viewport where the whole board fits the frame — minimal-move means it should not have stirred`,
        ).toBe(0);
      }
    });
  }

  test("the pause control freezes the clock, and the visitor's hand stands the take down", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");
    const act = theAct(page);
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    await expect(act.pause).toBeVisible({ timeout: 20_000 });

    // Pause: the control flips to Play (the director's clock advances only
    // while unpaused; the flip is the visible half of that contract).
    await act.pause.click();
    await expect(act.play).toBeVisible();

    // The visitor's hand on the STAGE outranks the script: a real (trusted)
    // press stands the take down, the strip says whose board it is now, and
    // the replay control remains the way back into the take.
    await act.section.getByTestId("pipeline-board").click({ position: { x: 20, y: 20 } });
    // MUTATION (watched red 2026-08-20): delete the `isTrusted` stand-down
    // listener from OnerStage. The take then stays merely PAUSED under this
    // click, so the strip keeps its last narration line instead of ACT.yours
    // and this line is the one that goes red. It isolates THIS assertion and
    // nothing below it: `expect` fails fast, so the Play-count line further
    // down never executes under this mutation and needs its own.
    await expect(act.strip).toHaveText(ACT.yours);
    await expect(act.replay).toBeVisible();
    // THE DISCRIMINATOR, and why it is both counts: a merely-paused take
    // still renders the toggle (reading "Play"), so `Pause` at zero is true
    // of pause AND of stand-down and proves nothing. Only the stood-down
    // state — the phase has left "playing" — clears the whole toggle.
    // MUTATION (watched red 2026-08-20), and it is NOT the one above: keep
    // the `isTrusted` listener and drop only `onPhase("done")` from
    // `takeOver`. The strip assertion passes, the `pause` count passes at 0,
    // and the `play` count reads 1 — which is also the direct proof that
    // both counts are needed, since the old single-count assertion would
    // have been green on that same defect.
    await expect(act.pause).toHaveCount(0);
    await expect(act.play).toHaveCount(0);
  });

  test("reduced motion disarms the take and rests the board", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    // The resting state is the live product, not a still: the board mounts.
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    // The strip says the setting is respected, and no transport renders —
    // there is nothing to pause and nothing to replay.
    const act = theAct(page);
    // MUTATION (watched red 2026-08-20): ACT.resting never swapped in.
    await expect(act.strip).toHaveText(ACT.resting);
    // THE TWO TRANSPORT COUNTS ARE DOUBLE-GATED, and the recipe that
    // forgot it was GREEN. Under reduced motion `disarmed = reduced !==
    // false` is true, so OnerStage returns the resting board before any
    // effect runs, every effect early-returns on `disarmed`, `start()` is
    // never reached, and `phase` can never leave "idle". Both inner gates in
    // WindowAct — `phase === "playing"` on the pause/play toggle,
    // `phase !== "idle"` on replay — therefore stay shut whatever `armed`
    // does. That is defence in depth and it stays; it just means dropping
    // `armed &&` alone reddens NOTHING here (run, and green in 758ms with
    // the gate gone from the served bundle), so each count needs the phase
    // seeded as well.
    // MUTATION (watched red 2026-08-20, own build): drop `armed &&` in
    // WindowAct AND seed `useState<OnerPhase>("playing")` — `pause`
    // received 1.
    await expect(act.pause).toHaveCount(0);
    // MUTATION (watched red 2026-08-20, own build): drop `armed &&` AND seed
    // `useState<OnerPhase>("done")` — `replay` received 1, resolving to
    // exactly one element. The pause count above passes first under this
    // one, which is what proves the two counts discriminate independently.
    await expect(act.replay).toHaveCount(0);
    // And no synthesized pointer exists to move.
    // MUTATION (watched red 2026-08-20): render the cursor in OnerStage's
    // `disarmed` branch. Single-gated, so this one needs no seeded phase.
    await expect(act.pointer).toHaveCount(0);
  });

  /**
   * The RAIL TAKES' reduced-motion disarm — the oner's contract, held for
   * the other two takes on the page. Until 2026-08-20 this was browser-pass
   * evidence only: the suite covered the oner's disarm and nothing covered
   * `RailTake`'s, though it is a separate implementation of the same
   * promise. Each rail is PARKED IN VIEW first, because the failure mode
   * worth money is not "the resting line renders at load" but "the arming
   * observer starts a take the moment the exhibit is seen".
   *
   * The transport counts inherit the oner trio's lesson verbatim: under
   * reduced motion `armed = reduced === false` is false, `start()` is never
   * reached, and `phase` cannot leave "idle" — so the inner gates
   * (`phase === "playing"`, `phase !== "idle"`) stay shut whatever `armed`
   * does, and dropping `armed &&` alone reddens nothing. Each count's
   * mutation therefore seeds the phase as well.
   *
   * MUTATIONS (each on its own `next build && next start`, watched red via
   * the design-side twin of these exact assertions — same bundle, same
   * browser, same arithmetic; this suite's own run is owed and canonical):
   *   · strip: `reduced ? resting : caption` in RailTake collapsed to
   *     `caption` — both rails' strips then hold their opening lines and
   *     the verdict strip assertion is the first to red. The review strip
   *     assertion rides the same ternary and is named, not claimed.
   *   · pause count: drop `armed &&` AND seed `useState<…>("playing")` —
   *     Pause renders on both rails, the verdict count reds first.
   *   · replay count: drop `armed &&` AND seed `useState<…>("done")` —
   *     Replay renders, same shape.
   *   · THE VERDICT'S RESTING STILL (added 2026-08-20, and watched red on
   *     THIS suite's own `next build && next start`, not on a twin): the
   *     exhibit's initial state in `ClaimsDescent` reverted from
   *     `useState(1)` to `useState(0)`, so it rests at `raw` — the take's
   *     opening beat, and the exact defect `RailTake`'s docblock warns
   *     about, since with motion off nothing ever winds it forward. The
   *     verdicts box then measures 0px and the reading reds with that
   *     number. Restored and green again, `shasum -a 256` identical.
   *
   * That reading REPLACED two lines that could not fail — `getByText` on
   * the chips with `toBeVisible`, which stays green with the exhibit
   * collapsed, because the clip comes from an ancestor and Playwright's
   * visibility check does not resolve it. The same suspicion, applied to
   * the rest of this test, found one more line weaker than its claim: the
   * `#needs-classification` check gates the queue's MOUNT, not the settle.
   * Both are stated at the assertions themselves.
   */
  test("reduced motion disarms both rail takes and rests their exhibits", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize(DESKTOP_1024_768);
    await page.goto("/");
    await expect(page.getByTestId("pipeline-board")).toBeVisible();

    for (const [name, resting] of [
      ["verdict", KEPT.resting],
      ["review", HELD_TAKE.resting],
    ] as const) {
      const rail = theRailTake(page, name);
      await rail.self.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
      // The strip says the setting is respected — the resting line, not the
      // opening narration a take would have started from.
      await expect(rail.strip).toHaveText(resting);
      // No transport renders: nothing is playing, so there is nothing to
      // pause and nothing to replay. Counts, not visibility — the controls
      // must not exist. (The review exhibit mounts the shipped queue, which
      // has buttons of its own, so the counts are by exact accessible name
      // rather than a bare role sweep.)
      await expect(rail.pause).toHaveCount(0);
      await expect(rail.play).toHaveCount(0);
      await expect(rail.replay).toHaveCount(0);
    }

    // And the resting states are the demonstrative stills each exhibit
    // declares (`RailTake`'s docblock: the resting state IS the initial
    // render): the verdict rests at SPLIT — both live chips expanded — and
    // the held mail rests SETTLED into the review queue, which the shipped
    // component announces by its own id.
    //
    // Through the BOX, and measured. Until 2026-08-20 these two lines read
    // `getByText("preview only"/"whole body")` with `toBeVisible`, which
    // cannot fail: a chip keeps its own 187x97.9 box when the exhibit is
    // collapsed, because the clip is an ancestor's `overflow-hidden` and
    // Playwright's visibility check does not resolve that (see
    // `theVerdictChips`). The height of the box that actually collapses is
    // the reading, and it is asserted with the number in the message.
    const verdict = theRailTake(page, "verdict");
    const chips = theVerdictChips(verdict.self);
    await expect(chips.preview).toHaveCount(1);
    await expect(chips.body).toHaveCount(1);
    const chipsBox = await chips.box.boundingBox();
    expect(
      chipsBox?.height ?? 0,
      `the verdict exhibit does not rest at split with motion off: its verdicts box measures ${chipsBox?.height ?? 0}px tall, so the two live chips are collapsed. With motion off the take never runs, so whatever the initial render holds is the entire exhibit this reader ever gets.`,
    ).toBeGreaterThan(0);
    // A backstop for the one state a height cannot see — laid out, but
    // `visibility: hidden`. It rides on the reading above (`expect` fails
    // fast) and is named rather than claimed: no mutation available here
    // produces it.
    await expect(chips.box).toBeVisible();
    // NOT A READING OF `settled`, and this line must not be read as one.
    // PROVED by mutation, 2026-08-20, own `next build && next start`:
    // `useState(true)` → `useState(false)` for `settled` in `ClaimsDescent`
    // — the held mail then does NOT rest settled, and the served HTML
    // carries the queue at `translate-y-2 opacity-0 aria-hidden="true"` —
    // and this whole test stayed GREEN. Playwright reads opacity-0 with a
    // layout box as visible, so the line passes in both beats. What it DOES
    // gate is that the shipped queue mounted at all (client-only, dated from
    // an effect, renders nothing until `today` lands), which is worth
    // keeping and is all it says. Covering the settle needs a handle on the
    // element that actually moves — the queue wrapper's `aria-hidden`, or
    // the mail body's own collapsed box — and that is a change to the
    // exhibit, left for its owner rather than made here.
    await expect(page.locator("[data-rail='review'] #needs-classification")).toBeVisible();
  });

  /**
   * SEED 6, and it closes the gap the count above leaves open.
   *
   * `toHaveCount(RAIL_COUNT)` counts nodes carrying `sticky top-20`. It was
   * green on the build where `#access` declared that class and the pin had
   * ZERO RANGE: the phase paced its copy as one 75vh screen, the section
   * collapsed to the rail's own height (sectionH 689 == railH 688), and a
   * sticky box with no runway simply translates with the scroll. `5c91e80`
   * fixed it, and nothing in either suite could have caught it — re-pacing
   * that copy back to one screen restores the exact defect with every gate
   * green. The visible cost was the import clip's chrome strip, play/pause
   * included, cropping above the fold while its body was still on screen: the
   * crop the whole board rework exists to kill, at the conversion surface.
   *
   * WHAT IS ASSERTED IS THE RELATION, NOT THE GEOMETRY. Each rail is walked
   * through its own band and its `top` sampled; the reading is how much of the
   * band it spent HELD at its sticky offset. The numbers in my table move with
   * every copy edit and none of them are pinned here — only the share, against
   * a threshold below the tightest real reading. It was 6.1% below #access's
   * 0.213 at 1512x600; #access no longer runs a rail (2026-08-20), and the
   * spine is five rails now with no decision rail among them. The tightest
   * reading that remains is the RULES rail's 0.312 at 1512x600, with ROW's
   * 0.314 at two corners just behind it (per the measured table in
   * `MIN_PIN_SHARE`, which is the one place those numbers live), and the
   * floor sits well under both. `MIN_PIN_SHARE` carries the table and says
   * why the floor is not being raised to close that gap back up.
   *
   * THIS SENTENCE SAID "REVIEW's 0.321 at 1024x1120" until 2026-08-21, which
   * contradicted the table it cites: the table's own argmin prose has read
   * rules-then-row-then-review since the 4:3 recapture. That is the FIFTH
   * time this file's prose has named the wrong corner, and the first four are
   * already confessed in `MIN_PIN_SHARE`. The pattern is always the same, a
   * number re-derived in prose instead of read off the table, so read it off
   * the table.
   *
   * Re-confirmed against a full production run on 2026-08-21, after the
   * decision phase lost the benchmark figure from the rules rail's own
   * runway: 30 of 30 readings clear the floor, the rules rail's worst is
   * 0.314 at 1024x600 and 1512x600, and overhang is zero everywhere.
   *
   * The pre-fix signature is a `top` that falls by exactly the scroll delta at
   * every sample (measured then, over six samples: 281 181 81 -19 -119 -219).
   * That reading earns zero pinned distance here — the plateau is counted
   * BETWEEN consecutive samples that both read the offset, and 1:1 translation
   * cannot produce two of those in a row at a 24px stride.
   *
   * EVERY rail, not just the one that broke. The spine's rails are the same
   * construction repeated, so the defect is available to all of them, and
   * the ones that did not break had no coverage of it either.
   *
   * SIX VIEWPORTS, AND THEY ARE THE CORNERS OF THE DESIGN RANGE rather than
   * a sample of it. This ran at 1024x768 alone on the reasoning that the pin
   * is a fact about the band and the rail and both are `vh`-paced — which is
   * false: a rail's exhibit is a fixed number of pixels tall in a fixed-width
   * column, so the ratio moves with the viewport and does NOT move
   * monotonically. A short viewport squeezes a rail against its own exhibit; a
   * tall one squeezes it against its phase's runway; and WIDTH moves both by a
   * third mechanism, which is what the three-viewport version still could not
   * see. The walked set is {1024, 1512} x {600, 768/949, 1080/1120}, six in
   * all: 1024x600 is the shortest the page is designed for; 768 is where the
   * original crop was found; 1512x600 is where the page's real minimum
   * lives, 0.213; 949 is where the viewport-tall staging's 0.170 hid (it
   * read 0.262 at 768, under a gate that only ran there); and 1512x1080 and
   * 1024x1120 are the TALL corners. HEIGHT EARNED ITS OWN CORNER because a
   * viewport-tall rail grows 1:1 with dvh while a content-paced band does
   * not, so the share bleeds away linearly above ~1075px — the take
   * rework's staging read 0.305 at 949 and 0.191 at 1512x1080 — and a
   * short-only set is structurally unable to see a tall squeeze, the same
   * way a single-width set was unable to see a wide one. `MIN_PIN_SHARE`
   * carries the readings and the argument for why the corners, and not a
   * midpoint, are the thing to walk.
   *
   * MUTATION-TESTED AT INTRODUCTION (2026-08-19, `next build && next start` in
   * a detached worktree, headless Chromium, 1024x768). `AccessPhase` restored
   * to its pre-`5c91e80` single-screen pacing — the defect itself put back,
   * not a synthetic break — and this went RED naming the rail:
   *
   *   rail 3 in #access: band 688px, rail 688px, runway 0px, pinned 0px at an
   *   offset of 80px. Rail top through the walk: 199.8 151.8 103.8 55.8 7.8
   *   -40.2 — the rail holds at its sticky offset for 0.0% of its band
   *
   * — pure translation, every reading a whole stride below the last, which is
   * the pre-fix signature exactly. Green again on the restored file (`shasum
   * -a 256` identical before and after), 18/18 across this suite, and steady
   * under `--repeat-each=3`.
   *
   * THE THREE DESCENT RAILS WERE MEASURED IN THAT SAME RUN AND PASSED, and
   * that is named rather than claimed as coverage: `expect` fails fast, so
   * their readings were evaluated but never watched go red. They run the one
   * code path `#access` reddened, so the path is proven able to fail; the
   * geometry of each of the three is not independently reddened.
   *
   * `#ACCESS` IS NO LONGER AVAILABLE AS THAT MUTATION (2026-08-20): the phase
   * has no rail to collapse. The re-mutation below — one descent rail's band
   * collapsed in-page at a time — is the live procedure now, and it covers
   * every rail the page has.
   *
   * The mutation restored a 688px band on a 688px rail — a 0px runway, where
   * the historical defect had 1px — and the reading is not sensitive only at
   * that extreme. Two consecutive samples inside the tolerance need about 20px
   * of real pin (a `PIN_STEP` stride, less `PIN_TOLERANCE` at each end), so
   * EVERY collapsed-band variant, the 689-vs-688 one included, reads 0px.
   *
   * RE-MUTATED at every restaging of the rails since, because each one changed
   * what a rail brings to its own pin and the guard has to be shown still able
   * to fail. Under the negative-margin staging, each clip rail's band was
   * collapsed in-page to its rail's own border height and each read RED on the
   * share — the decision rail at -0.012, the sync rail and #access at -0.023,
   * against 0.174 for the sync rail with the overhang left in, which is why
   * the share nets the overhang off. Under the current staging, where the box
   * is the exhibit and the margin is positive, the same collapse leaves a
   * runway of -56px and all three read 0.000 RED, at 1024x768 and at
   * 1512x949. RE-RUN 2026-08-19 with 1512x600 added and the rails' centring
   * constants re-derived: one rail collapsed at a time, three rails x four
   * walked viewports, 12/12 RED — each naming its own rail and a `top` that
   * falls a whole 24px stride at every sample — and green again on the
   * restored file (`shasum -a 256` identical before and after). The
   * assertions have not changed through any of it.
   */
  for (const viewport of [
    DESKTOP_1024,
    DESKTOP_1024_768,
    DESKTOP_1512_600,
    DESKTOP_1512,
    DESKTOP_1512_1080,
    DESKTOP_1024_TALL,
  ]) {
    const size = `${viewport.width}x${viewport.height}`;
    test(`every pinned rail holds at its sticky offset across its own band at ${size}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");

      // Arrival, before anything is measured: the rails exist only at `lg`+, and
      // the client tree is live (the board mounts from an effect), so what is
      // walked below is the pinned staging and not the stacked twin.
      await expect(page.getByTestId("pipeline-board")).toBeVisible();
      await expect(page.locator(STICKY_EXHIBIT)).toHaveCount(RAIL_COUNT);

      const walks = await walkRails(page);
      expect(walks, "the walk did not reach every rail").toHaveLength(RAIL_COUNT);

      for (const walk of walks) {
        const detail =
          `${walk.label}: band ${walk.bandHeight}px, rail ${walk.railHeight}px, ` +
          `overhang ${walk.overhang}px, runway ${walk.runway}px, pinned ${walk.pinned}px ` +
          `at an offset of ${walk.offset}px. Rail top through the walk: ${walk.trace}`;

        expect(walk.offset, `${detail} — the rail resolves no sticky offset`).toBeGreaterThan(0);

        // The walk genuinely traversed the band: the rail arrived below its
        // offset and left above it. Without this pair a rail that never moved at
        // all — one that had become `fixed`, or a band measured wrong — would
        // read as a flawless plateau, which is the shape this test exists to
        // stop shipping.
        expect(
          walk.approach,
          `${detail} — the walk started with the rail already at or past its pin, so the plateau below is not a measurement`,
        ).toBeGreaterThan(walk.offset + PIN_TOLERANCE);
        expect(
          walk.exit,
          `${detail} — the walk ended with the rail still at its pin, so it never left its band`,
        ).toBeLessThan(walk.offset - PIN_TOLERANCE);

        // Net the margin overhang off: it is pin the rail brings with it, not
        // pin the phase's flow column earned, and leaving it in would let a band
        // collapsed to its rail's own height still read a fifth of itself pinned.
        const share = (walk.pinned - walk.overhang) / walk.bandHeight;
        expect(
          share,
          `${detail} — the rail holds at its sticky offset for ${(share * 100).toFixed(1)}% of its band, under the ${MIN_PIN_SHARE * 100}% floor. A sticky column whose band is no taller than the column has nowhere to pin, so it translates with the scroll and carries its exhibit's chrome off the top of the fold — the defect 5c91e80 fixed at #access.`,
        ).toBeGreaterThanOrEqual(MIN_PIN_SHARE);
      }
    });
  }

  /**
   * SEED 1. The provenance line is the exhibit's last line and the page's
   * honesty guarantee about the two verdicts above it. This asserts it is
   * INSIDE the viewport at the shortest viewport the page is designed for,
   * in the stage where the verdicts are actually on screen.
   *
   * It asserts CONTAINMENT, not a margin. The clearance measured here on
   * 2026-08-20 (`next build && next start`, headless Chromium, 1024×600,
   * five-rail staging) is 7.2px — bottom 592.8 against a 600px fold, paused
   * at the split beat, and 7.2 is also the MINIMUM over the whole take at
   * 150ms sampling — but pinning that number would make a font-metric change
   * a CI failure, which is not what this guards. The margin is reported in
   * the failure message so a red run says how far out it went.
   *
   * REWRITTEN 2026-08-20, because the take restaging broke it in two stale
   * layers and the second hid the first: `.locator("p").first()` resolved to
   * `RailTake`'s new caps strip instead of the wall label (see
   * `theRailTake`'s docblock), and the split stage this test parked on had
   * become a transient beat of the 02b take. The text assertion failed
   * fast, so the containment lines below — the page's number-one honesty
   * guarantee — NEVER EXECUTED, and the fold was 10.6px broken at the
   * owner's working height with this test green-by-absence. The take's own
   * transport is the fix: ride to the split beat and PAUSE there, which is
   * both deterministic (the beat holds 3.8s against a ~100ms poll, and
   * Pause freezes the clock) and the exact scenario the defect was
   * measured in.
   *
   * AND IT LOST THE SAME BLOCK A SECOND TIME, in that very rewrite: the
   * split check below addressed the chips as `getByText("whole body")`,
   * which is SUBSTRING matching, and the beat's own narration line quotes
   * that phrase — strict-mode violation, and `expect` fails fast, so the
   * containment assertions had STILL never executed. They execute for the
   * first time from the commit that added `theVerdictChips` (2026-08-20).
   * Read 8045d5a's message with that in mind: "watched red on the reverted
   * fix: -10.6px through the new drive" was NOT measured through this spec —
   * this spec stopped at the chip locator, three lines above the margin —
   * but on a design-side twin of the drive using a different locator. The
   * red is real and reproduces here (see the recipe below); the instrument
   * named in that message was not this one.
   *
   * WATCHED RED, from this file, on this drive (2026-08-20, `next build &&
   * next start`, 1024x600): `ClaimsDescent.tsx` restored byte-exact from
   * 8fd2a30 — the `top-20` + `py-4` rails, the historical defect, not a
   * synthetic break — reds THIS test's containment assertion at -10.625px,
   * with the drive intact all the way to it. Green again on the restored
   * file (`shasum -a 256` identical before and after). The message that
   * assertion prints was itself watched, on a temporary floor of 1000: it
   * reports from the margin line, quoting the live clearance (7.19px).
   *
   * THE TOP-EDGE LINE RIDES ON IT, and this file names that rather than
   * claiming it: `box.y >= 0` is evaluated on every green run but has never
   * been watched red, because `expect` fails fast and no mutation available
   * to this staging pushes the line's TOP off — 8fd2a30's defect crops the
   * bottom only. It is a backstop against a future staging that pins the
   * exhibit past the top of the fold, not a reddened guarantee.
   */
  test("the exhibit's provenance line stays inside the fold at 1024x600", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    // The descent's boundary is the position of the second micro-beat within
    // the paired claims (`ClaimsDescent` measures it, rather than assuming a
    // half). So drive to that micro-beat's own paragraph — the thing the
    // boundary is derived from — instead of to a `[data-claim]` sentinel,
    // which the scroll-progress rewrite removed.
    // Addressed by the words the reader sees, which means a copy edit moves
    // it. The 2026-08-21 sweep rewrote this paragraph off "the shipped rules
    // layer" (an internals name the page no longer speaks) and this locator
    // went with it. Anchored on the shortest phrase that is unique to this
    // micro-beat and carries no vocabulary the voice gates can retire: it is
    // the SECOND reading that defines the boundary being measured.
    await centreOnText(page, /^So Applied reads it twice/);

    // The rail autoplays its take once in view: wait for the SPLIT beat —
    // the narration line is the beat's address, imported from the copy so a
    // retimed script cannot detach this — and hold it with the take's own
    // Pause. Split is the exhibit's tallest state and the one where the
    // verdicts are on screen, i.e. the stage the guarantee is about.
    const rail = theRailTake(page, "verdict");
    await expect(rail.self).toHaveCount(1);
    await expect(rail.strip).toHaveText(KEPT.narration[1], { timeout: 20_000 });
    await rail.pause.click();
    await expect(rail.play).toBeVisible();

    // Parked at split for real: the verdicts' box has actually opened. That
    // box is the element the collapse zeroes, so `toBeVisible` reads the beat
    // here — a chip cannot, see `theVerdictChips` — and the two chips are
    // then asserted present, one each.
    const chips = theVerdictChips(rail.self);
    await expect(chips.box).toBeVisible();
    await expect(chips.preview).toHaveCount(1);
    await expect(chips.body).toHaveCount(1);

    await settledHeight(page, "[data-rail='verdict'] > div");

    const provenance = rail.self.getByText(PROVENANCE);
    await expect(provenance).toHaveCount(1);
    const box = await provenance.boundingBox();
    expect(box, "the provenance line has no box — it is not rendered").not.toBeNull();
    const fold = await page.evaluate(() => window.innerHeight);
    const margin = fold - (box!.y + box!.height);

    expect(
      margin,
      `the provenance line is cropped at ${DESKTOP_1024.width}x${DESKTOP_1024.height}: its bottom sits ${-margin}px below the fold. It is the sentence that stops a visitor reading the live verdicts above it as verdicts on real mail.`,
    ).toBeGreaterThanOrEqual(0);
    // And it is genuinely on screen, not merely ending above the fold with its
    // top pushed off the other end by a sticky offset.
    expect(box!.y, "the provenance line starts above the viewport").toBeGreaterThanOrEqual(0);
  });

  /**
   * A BEAT LANDS WHILE THE RAIL IS PINNED — at any scroll speed a reader
   * actually reads at. The owner's report with his own screenshot
   * (2026-08-20): the dissolve beat arriving as the rail rode out of frame,
   * the next phase already on screen underneath. Measured on that build:
   * the take armed 488px before the pin (beats 0–1 burned on the approach),
   * the dissolve rendered 246px past release at 250px/s, and at ≥300px/s
   * the last two beats were UNREACHABLE — the clock froze below the
   * visibility threshold and never resumed (verified: parked 15s below,
   * caption still on beat 1). The cause was structural: the band is a
   * scroll DISTANCE, the clock is a TIME, and nothing related them.
   *
   * `RailTake` now holds a three-clause contract (its docblock): start at
   * the pin, a governor that compresses the clock when the visitor
   * outpaces it (floor 1 — parked means authored tempo), and a composed
   * ending for anyone who outruns even that. These three tests hold one
   * clause each.
   *
   * 250 px/s here because it is the owner's screenshot rate and inside the
   * governor's comfortable range (required sustained rate ~3.4 of the max
   * 8): every beat must not merely render but render PINNED. Measured on
   * the fixed build: all four beats at boxTopDelta 0, the last landing at
   * p=0.81 of the band.
   *
   * MUTATIONS (each on its own `next build && next start`, watched red
   * 2026-08-20 via the design-side twin of this exact drive; the suite's
   * own run is owed and canonical):
   *   · START-AT-PIN: the pin check dropped from `maybeStart` (start on
   *     visibility alone, the historical arming) — beat 0 renders ~490px
   *     before the pin and the FIRST transition's pin assertion reds.
   *   · GOVERNOR: the governor effect deleted — the take plays at rate 1
   *     and the dissolve's assertion reds while beats 0–1 stay green
   *     (measured: the dissolve never renders AT ALL at this speed — the
   *     freeze takes it, the original defect's exact shape — and the
   *     retained beat lands 564px past release).
   */
  test("the verdict take's beats all land pinned at a 250px/s read", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(() => {
      interface RailSample {
        t: number;
        boxTopDelta: number;
        cap: string | null;
      }
      const samples: RailSample[] = [];
      (window as unknown as { __rail: RailSample[] }).__rail = samples;
      const tick = () => {
        const box = document.querySelector<HTMLElement>("[data-rail='verdict']");
        if (box) {
          const r = box.getBoundingClientRect();
          samples.push({
            t: performance.now(),
            boxTopDelta: r.top - parseFloat(getComputedStyle(box).top),
            cap: box.querySelector("p[aria-live]")?.textContent ?? null,
          });
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    await page.goto("/");
    await expect(page.getByTestId("pipeline-board")).toBeVisible();

    // A constant-rate rAF drive through the rail's whole band, 900px of
    // approach included — the reader the page was measured failing.
    await page.evaluate(async (rate) => {
      const box = document.querySelector<HTMLElement>("[data-rail='verdict']")!;
      const cell = box.parentElement!;
      const stickyTop = parseFloat(getComputedStyle(box).top);
      const cellTop = cell.getBoundingClientRect().top + window.scrollY;
      const runway = cell.getBoundingClientRect().height - box.offsetHeight;
      const from = cellTop - stickyTop - 900;
      const to = cellTop - stickyTop + runway + 1100;
      window.scrollTo(0, Math.max(0, from));
      await new Promise((r) => setTimeout(r, 150));
      const t0 = performance.now();
      await new Promise<void>((done) => {
        const step = () => {
          const y = from + ((performance.now() - t0) / 1000) * rate;
          window.scrollTo(0, y);
          if (y < to) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      });
    }, 250);

    const samples = await page.evaluate(
      () =>
        (window as unknown as { __rail: { t: number; boxTopDelta: number; cap: string | null }[] })
          .__rail,
    );
    // First sample of each narration line, with the pin state it landed in.
    const landings = new Map<string, number>();
    let prevCap: string | null = null;
    for (const r of samples) {
      if (r.cap && r.cap !== prevCap) {
        if (!landings.has(r.cap)) landings.set(r.cap, r.boxTopDelta);
        prevCap = r.cap;
      }
    }
    for (const [index, line] of KEPT.narration.entries()) {
      const delta = landings.get(line);
      expect(delta, `beat ${index} ("${line.slice(0, 32)}…") never rendered at 250px/s`).toBeDefined();
      expect(
        Math.abs(delta!),
        `beat ${index} ("${line.slice(0, 32)}…") landed ${delta!.toFixed(0)}px off the pin — the beat arrived while the section was ${delta! < 0 ? "leaving" : "still arriving"}`,
      ).toBeLessThanOrEqual(3);
    }
  });

  /**
   * OUTRUN MEANS FOUND FINISHED, NEVER FROZEN MID-SENTENCE. The measured
   * defect: at ≥300px/s the clock froze below the visibility threshold
   * with the caption stuck on beat 1, permanently — parked 15 seconds, no
   * resume. A visitor who flicks past faster than the governor's ceiling
   * (~600px/s sustained) now finds the exhibit COMPOSED at its final beat
   * when the rail leaves below with its band spent — the closing act's own
   * "scrolled past means found finished" grammar, and the rail's resting
   * truth (the kept record) rather than a half-told story. Leaving ABOVE
   * mid-band still freezes: that visitor is coming back down.
   *
   * MUTATION (its own `next build && next start`, watched red 2026-08-20
   * via the design-side twin of this drive; suite run owed): the
   * compose-on-exit branch deleted from `RailTake`'s observer — after the
   * flick the phase reads "playing" and the caption holds an early beat,
   * both assertions red.
   */
  test("a 1200px/s flick past the verdict rail lands it composed, not frozen", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.getByTestId("pipeline-board")).toBeVisible();

    await page.evaluate(async (rate) => {
      const box = document.querySelector<HTMLElement>("[data-rail='verdict']")!;
      const cell = box.parentElement!;
      const stickyTop = parseFloat(getComputedStyle(box).top);
      const cellTop = cell.getBoundingClientRect().top + window.scrollY;
      const runway = cell.getBoundingClientRect().height - box.offsetHeight;
      const from = cellTop - stickyTop - 900;
      const to = cellTop - stickyTop + runway + 1100;
      window.scrollTo(0, Math.max(0, from));
      await new Promise((r) => setTimeout(r, 150));
      const t0 = performance.now();
      await new Promise<void>((done) => {
        const step = () => {
          const y = from + ((performance.now() - t0) / 1000) * rate;
          window.scrollTo(0, y);
          if (y < to) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      });
    }, 1200);
    // Parked below — the frozen-forever window the defect lived in.
    await page.waitForTimeout(2500);

    const rail = page.locator("[data-rail='verdict'] [data-take-phase]");
    await expect(rail, "the take is still 'playing' under a parked visitor who has left").toHaveAttribute(
      "data-take-phase",
      "done",
    );
    await expect(
      theRailTake(page, "verdict").strip,
      "the caption froze mid-take instead of composing the ending",
    ).toHaveText(KEPT.narration[3]);
  });

  /**
   * PARKED MEANS AUTHORED TEMPO — the governor may only borrow speed, never
   * keep it. The take language the owner chose off the lab is a paced
   * story; a governor bug that leaves the rate above 1 while the visitor
   * is still would compress the very performance the rails exist for, and
   * nothing else on this page would notice: every beat still renders, in
   * order, pinned. So the clock is timed: parked at the pin, the dissolve
   * (authored at raw+6.8s) must not arrive early. The floor is 0.8 of
   * authored — rAF jitter only ever makes a clock LATE, so the only thing
   * that can arrive early is a rate above 1.
   *
   * MUTATION (its own `next build && next start`, watched red 2026-08-20
   * via the design-side twin; suite run owed): the governor's rate floor
   * raised from 1 to 3 — the parked dissolve arrives at ~2.3s against an
   * authored 6.8s and the timing assertion reds.
   */
  test("a parked verdict take plays at the authored tempo", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.getByTestId("pipeline-board")).toBeVisible();

    // Park a breath past the pin start and stay there.
    await page.evaluate(() => {
      const box = document.querySelector<HTMLElement>("[data-rail='verdict']")!;
      const cell = box.parentElement!;
      const stickyTop = parseFloat(getComputedStyle(box).top);
      window.scrollTo(0, cell.getBoundingClientRect().top + window.scrollY - stickyTop + 8);
    });
    const rail = theRailTake(page, "verdict");
    await expect(rail.strip).toHaveText(KEPT.narration[0], { timeout: 10_000 });
    const t0 = Date.now();
    await expect(rail.strip).toHaveText(KEPT.narration[2], { timeout: 15_000 });
    const elapsed = Date.now() - t0;
    expect(
      elapsed,
      `the dissolve arrived ${(elapsed / 1000).toFixed(1)}s after the raw beat against an authored 6.8s — the governor is accelerating a parked take`,
    ).toBeGreaterThanOrEqual(0.8 * 6800);
  });

  /**
   * The closing act PLAYS ITSELF — once, slowed, to completion — and HOLDS.
   * Retargeted 2026-08-19 (owner's call) off the scroll-scrub contract this
   * test held for a few hours: the ending is narration, not an artifact the
   * reader operates, so the playhead belongs to ClosingAct's own clock once
   * the scene is in view, and scrolling back up finds it FINISHED rather
   * than un-drawn. The rewind assertions left with the scrub.
   *
   * The drive is the case that has failed every prior build: a flick
   * straight to max scroll. The pin plus the band's position (last section,
   * footer excepted) is what guarantees the scene is still on screen there,
   * so the poll below is asserting the whole reconciliation — the play
   * cannot be outrun, and it genuinely reaches its own end (~3.7s at
   * AUTO_RATE; the poll's timeout is comfortably past it, so a stalled clock
   * fails rather than flakes).
   *
   * The verdict's landing is asserted against the page's OWN declared seat —
   * the `.act__ripple` circle is drawn at the baseline seat and never moves —
   * so this is not a golden pixel: it says "the dot ends where the scene says
   * the full stop goes".
   */
  test("the closing act plays itself once in view, and holds composed", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    const compose = () =>
      page.evaluate(() => {
        const centre = (sel: string) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        };
        const ask = document.querySelector(".act__ask");
        const stroke = document.querySelector(".act__word .act__draw path");
        return {
          playing: document.querySelector("section.act")?.className.includes("act--play") ?? false,
          dot: centre(".act__dot"),
          seat: centre(".act__ripple"),
          lane: centre(".act__guide"),
          askOpacity: ask ? Number(getComputedStyle(ask).opacity) : -1,
          dashoffset: stroke ? getComputedStyle(stroke).strokeDashoffset : "unset",
        };
      });

    // Nothing has played yet: the band is below the fold at load. Read AFTER
    // proof that the client tree is live — the board only mounts from an
    // effect, so waiting on it means the closing act's own scroll binding has
    // had its chance to fire. Without that wait this assertion passes on a
    // page that simply has not hydrated, which is a check that cannot fail.
    //
    // The playhead, not the class: `act--play` is server-rendered now, so it
    // says nothing about whether anything has happened.
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    expect(await playhead(page), "the closing sequence advanced before it was seen").toBe(0);

    await page.evaluate(() => window.scrollTo({ top: 1e7, behavior: "instant" }));
    // The play runs on its own clock now; the poll's window is sized to the
    // slowed sequence, not to a scroll.
    await expect
      .poll(async () => (await compose()).askOpacity, { timeout: 10_000 })
      .toBe(1);

    const played = await compose();
    expect(played.playing).toBe(true);
    expect(played.dot, "the verdict never entered").not.toBeNull();
    expect(played.seat, "the scene declares no seat for the full stop").not.toBeNull();
    // It fell out of the lane…
    expect(
      played.dot!.y - played.lane!.y,
      "the verdict never left the lane — it does not punctuate the wordmark",
    ).toBeGreaterThan(100);
    // …and seated itself exactly where the scene says the full stop goes.
    expect(Math.abs(played.dot!.x - played.seat!.x)).toBeLessThanOrEqual(2);
    expect(
      Math.abs(played.dot!.y - played.seat!.y),
      "the verdict did not seat on the wordmark's baseline",
    ).toBeLessThanOrEqual(2);
    // The sentence itself finished drawing.
    expect(played.dashoffset).toBe("0px");

    // The playhead reached the end of the sequence rather than merely "far
    // enough" — a clock that stalls short would leave the page's closing
    // image permanently a few frames from finished and nothing above would
    // notice.
    expect(await playhead(page), "the sequence never reached its own end").toBeCloseTo(2.05, 2);

    // It HOLDS. The ending is watched once, like the sentence it draws:
    // leaving and returning finds the finished frame — no rewind (the scrub's
    // contract, retired), no surprise replay (the fire-once build's defect).
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.evaluate(() => window.scrollTo({ top: 1e7, behavior: "instant" }));
    await page.waitForTimeout(400);
    const returned = await compose();
    expect(await playhead(page), "the finished play did not hold").toBeCloseTo(2.05, 2);
    expect(returned.dashoffset, "the drawn sentence came apart on return").toBe("0px");
    expect(
      Math.abs(returned.dot!.y - returned.seat!.y),
      "the verdict did not stay seated",
    ).toBeLessThanOrEqual(2);
  });

  /**
   * The nav's one persistent path. A URL-hash assertion would pass with no
   * target element at all, so this measures where the section LANDED: below
   * the sticky header (that is what `SectionShell`'s `scroll-mt` buys) and
   * inside the fold.
   */
  test("the nav's access anchor lands on the access section", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    await page.getByRole("link", { name: /^Get access$/i }).click();
    await expect(page).toHaveURL(/#access$/);

    const heading = page.getByRole("heading", { name: /One hundred seats/i });
    await expect(heading).toBeVisible();

    const landing = await page.evaluate(() => {
      const nav = document.querySelector("header");
      const section = document.querySelector("#access");
      if (!nav || !section) return null;
      return {
        navBottom: nav.getBoundingClientRect().bottom,
        sectionTop: section.getBoundingClientRect().top,
        fold: window.innerHeight,
      };
    });
    expect(landing, "there is no #access section for the nav to reach").not.toBeNull();
    expect(
      landing!.sectionTop,
      `the access section landed ${landing!.navBottom - landing!.sectionTop}px UNDER the sticky nav`,
    ).toBeGreaterThanOrEqual(landing!.navBottom - 1);
    expect(landing!.sectionTop, "the access section landed below the fold").toBeLessThan(
      landing!.fold,
    );
  });

  for (const [label, viewport] of [
    ["1024", DESKTOP_1024],
    ["768", TABLET_768],
    ["375", MOBILE_375],
  ] as const) {
    test(`no horizontal overflow at ${label}px`, async ({ page }) => {
      const watch = startConsoleWatch(page);
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(
        page.getByRole("heading", { name: /You lose the email/i }),
      ).toBeVisible();
      await expectNoHorizontalOverflow(page);

      // Below `lg` the whole page is the still/inline staging, so walk it to
      // the end — the closing act's 1200-unit scene and the descent's inline
      // snapshots are the parts most likely to spill.
      await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight }));
      await page.waitForTimeout(300);
      await expectNoHorizontalOverflow(page);

      expect(watch.errors, watch.errors.join("\n")).toEqual([]);
    });
  }
});
