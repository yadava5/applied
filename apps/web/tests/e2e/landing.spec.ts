import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";
import { ACT } from "../../components/marketing/copy";

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
 *  failure. The decision rail squeezes by the same mechanism and is the
 *  page's tightest now, so the height corners matter MORE than they did. */
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
 *  walked. 1512 is where the owner works; every width from 1280 up reads the
 *  same, the container being capped at `max-w-6xl`. */
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

/** The exhibit's closing sentence — the honesty guarantee, matched on the
 *  clause that carries it rather than on the whole sentence, so a wording
 *  tweak that keeps the promise does not turn CI red. */
const PROVENANCE = /A synthetic email .* computed live in this tab/;

/** A pinned rail (`lg`+ only) — the page's spine is three of them, one per
 *  descent phase, sides alternating (`ClaimsDescent`'s docblock). It was
 *  four: `#access` pinned the import recording until that clip was retired
 *  on 2026-08-20, and with nothing honest to pin the phase collapsed to a
 *  single column rather than borrow an exhibit (`AccessPhase` argues it). Below `lg` each
 *  screen carries its own inline snapshot, and those are the copies this must
 *  NOT measure.
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
 * MEASURED on `next build && next start` (2026-08-20, five-rail restaging),
 * verdict / rules / review / row / retention, at each of the six viewports
 * this walk runs — taken with the design-side walk (same band arithmetic,
 * stable-top plateau at tolerance 2 / step 24, no overhang netting, which
 * is inert on this page anyway); this suite's own run is owed and is the
 * canonical reading:
 *
 *   1024x600    0.570  0.354  0.343  0.543  0.746
 *   1024x768    0.547  0.469  0.357  0.647  0.773
 *   1512x600    0.570  0.341  0.371  0.543  0.746
 *   1512x949    0.531  0.578  0.343  0.705  0.777
 *   1512x1080   0.533  0.619  0.333  0.746  0.798
 *   1024x1120   0.536  0.628  0.321  0.765  0.800
 *
 * The tightest is the REVIEW rail at 0.321 (1024x1120) — the viewport-tall
 * take rail over two paced beats, the same dvh-paced shape whose asymptote
 * the old decision rail measured at ~0.29 beyond range — with the RULES
 * rail's short edge next at 0.341 (1512x600). The floor keeps more
 * clearance than the old spine's tightest corner and is deliberately NOT
 * raised to suit, because the number it has to survive is the next
 * restaging's, not this one's.
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
   * THE SHOT IS A SHOT. Production played a whole take with the camera
   * parked — the pointer pressed the day bar, the board filtered, and the
   * frame showed the shrunken board centred in a void, because the script's
   * zooms were authored at absolute scale 1 (owner screenshot, 2026-08-20).
   * Every gate was green: the take's logic ran, so nothing red existed to
   * see. This is the assertion that was missing: the director now writes
   * `data-cam-scale` on the frame each time it applies the camera
   * (`applyCam`), and a take must actually TRAVEL — the range between the
   * shallowest and deepest shot must be a real push-in, not jitter.
   *
   * 1024x1120 DELIBERATELY, not the working 1024x768: at tall frames the
   * establishing fit clamps to 1.0 and the parked-camera defect reads a
   * range of ~0.0, while at short frames the sub-1 establishing fit gives
   * even a parked camera a spurious range (0.52 → 1.0 at 600 tall). The
   * tall corner is where the defect is visible and ONLY the fix passes:
   * fixed, the range there is ~1.26 (1.000 establishing → 2.26 close-up,
   * held for seconds at a time, so 250ms sampling cannot miss it).
   *
   * MUTATION (watched red 2026-08-20, via the design-side twin of this
   * exact poll — same bundle, same browser, same arithmetic; this suite is
   * not run by the frontend agent): `punchTo` reverted to
   * `zoomTo(target, 1)`. The take plays to completion, every narration
   * assertion above stays green, and the observed range collapses to 0.000
   * — this line is the only one that reds. Restored and watched green the
   * same way; a first run of this suite itself is owed and is the
   * canonical proof.
   */
  test("the camera arrives: the take's shots actually travel", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 1120 });
    await page.goto("/");
    await expect(page.getByTestId("pipeline-board")).toBeVisible();

    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    await expect
      .poll(
        async () => {
          const v = await page.evaluate(
            () => document.querySelector<HTMLElement>("[data-cam-scale]")?.dataset.camScale,
          );
          if (v) {
            const n = Number(v);
            min = Math.min(min, n);
            max = Math.max(max, n);
          }
          return max - min;
        },
        { timeout: 30_000, intervals: [250] },
      )
      .toBeGreaterThanOrEqual(0.5);
  });

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
   * 0.213 at 1512x600; #access no longer runs a rail (2026-08-20), so the
   * tightest of the readings that remain is the decision rail's 0.337 and
   * the floor sits well under it. `MIN_PIN_SHARE` carries the table and says
   * why the floor is not being raised to close that gap back up.
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
   * 2026-08-15 (`next build && next start`, headless Chromium, 1024×600) is
   * 2.9px — bottom 597.1 against a 600px fold — but pinning that number would
   * make a font-metric change a CI failure, which is not what this guards.
   * The margin is reported in the failure message so a red run says how far
   * out it went.
   */
  test("the exhibit's provenance line stays inside the fold at 1024x600", async ({ page }) => {
    await page.setViewportSize(DESKTOP_1024);
    await page.goto("/");

    // The descent's boundary is the position of the second micro-beat within
    // the paired claims (`ClaimsDescent` measures it, rather than assuming a
    // half). So drive to that micro-beat's own paragraph — the thing the
    // boundary is derived from — instead of to a `[data-claim]` sentinel,
    // which the scroll-progress rewrite removed.
    await centreOnText(page, /^So the shipped rules layer runs on it twice/);

    // Arrived at the SPLIT stage: the wall label names it and both live
    // verdict chips have actually expanded (collapsed `grid-rows-[0fr]` gives
    // them a zero-height box, so `toBeVisible` discriminates).
    //
    // The spine runs three rails, so the verdict's is picked out by the
    // one thing only it holds at `lg`+: the provenance line itself. (The
    // retention record carries the same line, but in the FLOW column — the
    // clip rails hold recordings, not emails.)
    const exhibit = page.locator(STICKY_EXHIBIT).filter({ has: page.getByText(PROVENANCE) });
    await expect(exhibit).toHaveCount(1);
    await expect(exhibit.locator("p").first()).toHaveText("The same body, classified twice");
    await expect(exhibit.getByText("preview only")).toBeVisible();
    await expect(exhibit.getByText("whole body")).toBeVisible();

    await settledHeight(page, `${STICKY_EXHIBIT} > div:last-child`);

    const provenance = exhibit.getByText(PROVENANCE);
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
