# Landing B — what the browser actually shows

Claude-in-Chrome pass, 2026-08-19, against the deployed preview of
`feat/landing-variants` @ `09ed3ce` (alias
`jobtracker-web-git-feat-landing-912663-…`), viewport 1512 x 949.

This supersedes guesswork about durations. Two of the three complaints
Ayush raised are reproduced here with a mechanism; one turns out to be
deliberate.

---

## The instrument lied twice. Both are recorded so nobody re-reports them.

1. **A fully black hero board.** The first screenshot after navigation showed
   the board's chrome bar drawn and its interior pure black. The DOM at that
   moment already held real rows at `opacity: 1`. It was a paint-timing
   artifact of screenshotting before hydration settled, not a defect.
   *(There is a small real residue: the frame paints before its contents, so a
   slow connection does show an empty box briefly. Low priority.)*

2. **Ghosted, double-exposed board rows at scroll 1900.** Screenshotting
   immediately after an instant `scrollTo` catches the act mid-transition:
   large bold rows composited over normal-size dates bleeding through a
   semi-transparent detail pane. After a 3s wait at the same offset the frame
   composed perfectly. **The composition is not broken.**

But finding 2 is the door to the real defect, below.

---

## The real defect: the choreography is time-based, the trigger is scroll-based

`components/marketing/tempo.ts` defines the act as a fixed sequence:

| beat | source | ms |
|---|---|---|
| camera pan | `LandingBoard` transition | 700 |
| verdict breath | `VERDICT_BREATH_MS` | 1800 |
| row travel | `VERDICT_TRAVEL` | 1400 |
| settle before the pane docks | `VERDICT_SETTLE_MS` | 200 |

Beats overlap, but the observed wall-clock settle from a cold scene entry is
**about 3 seconds**. Measured directly: at offset 1900 the caption read
"The offer lands, and the row moves without you."; three seconds later,
without any further scrolling, it read "The row opens on the mail that moved
it." The scene advanced on its own.

`WindowAct` starts these timers from an `IntersectionObserver` sentinel. So
entering a scene fires a ~3s timeline that then runs **independently of the
scroll**.

Now the runway. The act's section is `lg:h-[270vh]` = **2562px**, and the
pinned board is **839px** tall, leaving roughly **1723px** of pinned scroll
for **three** scenes — about **574px each**.

A trackpad flick moves 1000–2000 px/s. So each scene gets **0.3 to 0.6
seconds** of dwell against a **3 second** choreography.

**The act needs five to ten times the runway it has, or it must stop being
timer-driven.** This single fact explains every symptom Ayush reported:

- *"it can hardly be seen what just happened"* — the row is still travelling
  when the reader has already left the scene.
- *"it's too fast, and by the time user gets to the full view, it already
  happened"* — the timeline ran while the scene was off-centre.
- Two previous passes adjusted durations and failed. Lengthening a timer
  inside a runway this short makes it strictly worse. **Do not adjust a
  duration again.**

### The fix shape

Bind the choreography to **scroll progress**, not to elapsed time: the row's
position between stage groups becomes a function of how far through the
pinned runway the reader is. Scrubbing up un-does it; stopping halfway holds
it halfway; nobody can outrun it. `motion` v13 (already a dependency) does
this with `useScroll` + `useTransform`. Reduced motion keeps the present
composed-immediately path.

Independently, the fade must be decoupled from the travel — the earlier
Playwright pass measured row opacity animating 0→1 across the same 1.4s as
the travel, so the row sits at 0.44 opacity at 44% of its journey and is only
legible once stopped. Fade in over ~150ms, then travel.

---

## The dead black space is real, and it is section 3

The "preview ends before the verdict" section is a two-column grid
**3152px tall** whose right column is a `sticky top-20` panel only
**421px** tall (growing to ~470px once composed).

Measured gaps at offset 3600, after the section had fully composed:

- ~175px of empty black above the left column's first paragraph
- ~180px of empty black in the left column between the tally exhibit and the
  next heading
- ~320px of empty black in the right column below the sticky panel, and it
  stays empty for the remaining ~2.5 viewports of the section

So a 421px card is pinned in a 949px viewport with roughly half a screen of
nothing beneath it, for over three screens of scrolling. That is exactly the
"weird spacing and black space" in Ayush's screenshot.

**Fix shape:** either the sticky panel earns the full column height (more
exhibit, staged as the reader descends), or the section stops being a sticky
two-column and becomes a normal alternating rhythm. Do not solve it by
adding filler copy — the complaint that "all the cards look the same" was
diagnosed as too much text, not too little.

---

## "The right pane never closes" is deliberate, not a bug

`WindowAct` carries this in its own source:

> Whether the verdict has already landed. The scene index goes back down when
> the reader scrolls up; the board's state does not.

The scene index is reversible; the board's state is a latch. Scrolling back up
replays the captions over a board that stays settled with the pane open.

That was a considered choice — a demo that un-does itself reads as a loop
rather than as an event. But Ayush has now said twice that it reads wrong.
**Reverse it**: make the board state a pure function of scene index, so the
act is fully reversible in both directions. Then the "revisited scene 0"
caption needs re-examining, because it currently narrates a settled board.

---

## Also seen, lower priority

- The `applied.` wordmark in the header renders in a monospace face. Confirm
  it is an intentional logotype and not the default-mono failure mode.
- The board frame paints before its rows on a cold load.

---

## What must be verified with Playwright, not here

Claude-in-Chrome throttles `requestAnimationFrame` in a background tab — an
`await` loop over eight scroll offsets froze the renderer and timed out. It
cannot measure motion timing. Everything above is either static geometry or a
settled composition, which it can see honestly.

The **continuous-scroll** experience — what a reader flicking through actually
sees frame by frame — needs a Playwright recording with smooth programmatic
scroll and frame extraction, on `next build && next start`, never `next dev`.
