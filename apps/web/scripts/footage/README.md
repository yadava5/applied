# Product footage

Short looping clips of the real app, for the landing page's artifact column.

```
pnpm footage                 # from apps/web — rebuilds every clip from scratch
```

That builds the app, serves it, records the UI, composes the clips with Remotion,
encodes them, and checks the result. Output lands in `apps/web/public/footage/`.

Clips go stale as the UI changes, which is why regeneration is one command. **A
clip nobody can re-render rots into a lie about a product that no longer looks
like that.**

## The covenant

Revised 2026-08-20, when `one-letter` needed a camera that moves. The old rule
read: *"Everything in these clips is the product. No fake cursors, no invented
UI, no motion graphics laid over the footage."* That sentence was doing two
jobs and only naming one of them, so a shot that moved the frame had nothing to
be measured against. The revision separates them and states the test.

**Everything inside the frame is the product.** Every pixel of every clip is a
surface the app painted, recorded off a running production build. No invented
UI, no motion graphics laid over the footage, no state composited in afterwards.

**Where the frame is, is the camera's.** Choosing a rectangle, moving that
rectangle across the recording, and cutting whole segments out of the take are
presentation — the decisions a lens and a splice make. They were always being
made here: every clip in this directory is already a crop, already re-timed
onto a hold/play/hold arc, already cross-dissolved back to its own opening.
Letting the rectangle *move* adds no new power to lie. It adds reach. The
surface this pipeline records is over a thousand CSS px wide and the picture
the page gives it is 478, so with a stationary window the only shots that exist
are the ones that fit inside one.

The line between the two is **provenance**, and it is testable: *anything
inside the frame must have been produced by the running app during the take;
anything about the frame must be disclosed here.* So:

- **Allowed, disclosed per clip.** Crop, pan and tilt; where the camera holds
  and where it moves; cutting whole segments; the cross-dissolve at the loop
  seam. A tracked clip's dissolve joins two camera POSITIONS as well as two
  moments — `one-letter` closes its loop by dissolving the seated row back
  into the letter, which is a join, not a claim that one became the other in
  that direction. Every clip's row below says what its camera did.
- **Allowed, and not yet used.** A pointer synthesized AT CAPTURE TIME — drawn
  into the page by the same events that drove the take, so the frame shows
  what the recorded session actually did. Nothing here needs one: every scene's
  input is an event dispatched at a shipped control, and none of them draws a
  cursor. A pointer added to a finished recording is a different thing and
  stays banned; it would be a claim about a session that did not happen.
- **Banned, unchanged.** Invented UI. Graphics drawn over frames. A cursor
  painted in post. And re-timing that changes what the recording claims —
  speeding a wait up so the product looks quicker than it is, or stretching a
  flicker until it reads as a considered animation. Segments come out whole or
  not at all, and what is left plays at 1x.

The reason to put a video on a marketing page instead of a diagram is that it
is real. A camera does not make it less real. Drawing on it does — and so does
a rule loose enough that nobody can tell which was done.

## The clips

| file | what it shows | length | webm | mp4 |
| --- | --- | ---: | ---: | ---: |
| `gmail-connects` | The Gmail card at "Not connected", the one permission Google is asked for, and the same card at "Connected". **Held back — not in `CLIPS`, not under `public/footage/` (2026-08-19); see the hand-recorded section below.** | 6.7s | 83.5 KB | 325.0 KB |
| `board-syncs` | One press of Sync: the counters go 17 filed · 14 open → 19 · 16, `APPLIED` 10 → 12, and the strip says "2 filed, 3 already known". | 4.9s | 106.3 KB | 61.1 KB |
| `one-letter` | **Tracked — the frame moves.** A card open on the mail behind a Kestrel Dynamics row: an assessment invitation, filed `assessment` at 97%, naming a deadline of Aug 22. The card is closed, the worklist expands into the space it held (`PipelineBoard`'s own layout animation — the tracked row goes 632→1036 px wide and un-wraps 68→42 tall, settled in 202 ms), and the camera tilts up to the row's own `due in 2d · Aug 22` tag and then tracks left into the ASSESSMENT group. | 8.1s | 365.5 KB | 490.4 KB |
| `rules-read-the-body` | A rejection typed into the shipped rules layer. The verdict holds at `OTHER 50%` through the preamble, flips to an amber `REJECTION 70%`, and lands green at `90%` — over the bar where layer 1 answers alone. | 10.9s | 312.0 KB | 154.4 KB |

`import-classifies` was here and is gone (2026-08-20). It never showed the file
being chosen and what it did show ran past too fast to read, and the owner
retired it rather than have it re-cut a third time; `clips.mjs` carries the
whole account and where the capture choreography still lives. Its three
artifacts came out of `public/footage/` with it — 585 KB that had been
shipping on every deploy — and `verify.mjs` now fails the run if any file in
that directory belongs to no clip in `CLIPS`, which is the check that would
have caught `gmail-connects` doing the same thing.

The row above it was stale before that: `rules-read-the-body` was re-timed to
per-keystroke typing on 2026-08-19 (5.0s → 10.9s) and this table still said
5.0s. The lengths and byte counts here are read off `manifest.json` after the
2026-08-20 render; the old row's "2.25s–2.45s" reading of the amber beat was
taken on the 5.0s take and has NOT been re-measured on the current one, so it
is not restated.

Each ships with a `.jpg` poster and is listed in `manifest.json` with its real
byte count. **Every length and byte figure above except `one-letter`'s was
stale until 2026-08-20** — they described the 30fps encodes, and the 2026-08-19
retime to 60fps moved all of them (it also doubled `rules-read-the-body`'s
duration outright, 5.0s → 10.9s). They are re-read off the committed manifest
now. A table of bytes nobody re-reads is the same failure as a clip nobody can
re-render.

**The poster is the LANDED END STATE, not the first frame** — changed
2026-08-19, and `clips.mjs`'s `POSTER_AT` is where the frame is chosen. First
frame was the original brief, and a loop's first frame is its "before" by
construction, so `rules-read-the-body.jpg` was an empty BODY field under
`OTHER 50%` and the line "below 0.90 — the full pipeline would defer to e5 /
SetFit": the product not having done the thing, stated twice. The poster is
what a reduced-motion visitor, a data-saver visitor and anyone who scrolls past
without playing sees INSTEAD of the recording, so it has to carry the argument
on its own. `gmail-connects` is the exception and still shows its first frame,
because it is not re-rendered by this pipeline.

**The encode is 1152px wide** (`OUT_WIDTH` in `remotion/Root.tsx`), which is
the capture's own native device-pixel width: the scenes crop at or under 576
CSS px and record at `--force-device-scale-factor=2`, so `Clip.tsx`'s
`k = width / (scene.camera?.width ?? scene.crop.width)` lands on exactly 2.0
and nothing is scaled up. That is also what fixes a tracked clip's frame at
576 CSS px and leaves it no room to zoom — `scenes.mjs` argues it where the
camera is defined.
It was 832 — twice the 26rem artifact column the clips were first placed in —
and that column no longer exists. At the 640-768 CSS px the landing shows them
at, 832 covered 54% of a 2x screen's native pixels; 1152 covers 90% at 640.
Raising it further would upscale.

**Both encodes ship, and NEITHER carries audio** — `render.mjs` passes
`muted: true` since 2026-08-20. Every clip before that shipped a real silent
track (Opus in the webm, AAC in the mp4, ~317 kbit/s declared) because
Remotion muxes one when it cannot yet see the asset list. The comment in
`render.mjs` claimed the clips were "silent by construction"; silent is not
absent, and on the mp4s the track was most of the file — `board-syncs` went
263.7 KB → 61.1 KB and `rules-read-the-body` 602.4 KB → 154.4 KB.

**Which also inverted the codec comparison, and this README used to state the
old one as fact.** With the audio in, VP9/WebM measured 2.1–3.9x smaller than
the H.264 fallback. With it out, the H.264 is SMALLER — 0.57x the webm on
`board-syncs`, 0.49x on `rules-read-the-body` — because what the old ratio was
mostly measuring was AAC against Opus. Whether the ladder should therefore
serve the mp4 first is a real question and a quality one (VP9 at CRF 34 and
H.264 at CRF 26 are not the same quality point, and the answer has to be
LOOKED at on the contact sheets at the 478px these render at), so it has not
been changed on byte counts alone. It is the open decision here.

The page walks the two encodes IN SCRIPT — one `src` at a time, webm then
mp4 — rather than as two `<source>` children. `<source>` is a selection list,
walked once before the first byte decodes, so an element that dies later has
no fallback left; two clips shipped frozen on the live page that way.
`components/marketing/clipPlayback.ts` argues it and
`tests/unit/clip-playback.test.mjs` drives it.

Every clip is well under the 500 KB budget on the modern codec; `render.mjs`
fails the run if one is not.

**A camera move costs about 3.4x, and it is the codec's advantage that it
spends.** `one-letter` is 365.5 KB of WebM against `board-syncs`' 106.3 KB for
a picture the same size and 3.2s more of it — VP9's win here comes from large
areas that do not change between frames, and a frame that is travelling has
none. A Safari visitor who takes the H.264 fallback pays 490.4 KB, the
heaviest single artifact on the page. **The budget was NOT raised.** It holds
as it stands, at 73% on the codec the gate measures, and it is worth keeping
tight: a second tracked clip would be a decision to make on its merits, not
one that slips in under a ceiling raised for the first. What must not happen
is the budget being met by lifting CRF — the encode's quality is the thing
the 1152px width exists to protect.

`one-letter`'s two encodes still carry the silent audio track (verified with
ffprobe, 2026-08-20): they were rendered before the strip described above, and
they ship as rendered rather than being re-derived — the take is
owner-approved and a re-capture is not guaranteed to reproduce it. The next
deliberate re-render of this clip inherits the strip and should shave the mp4
in particular; until then these two files are the one place the "silent by
construction" claim above does not yet reach.

Which claim each clip is relevant to is a design decision and lives with the
page, not here. Nothing in this directory imports from `components/marketing/`
or the other way round.

## Where they come from

Two of the three shipped clips are captured from **`/demo`**, which is public
and needs no login. That is deliberate and must stay that way: the owner's real
account holds genuine job applications with real employer names and real
rejections, and none of that goes on a public marketing page. `/demo` runs the
same shipped components over fixture data. The third, `one-letter`, captures a
different fixture for a reason argued under the table below — the rule it
keeps is the same one, and the components are the same components.

(No count is given on purpose. The number moves every week, and the one place it
was actually observed here — the tail of the OAuth recording — read *42 filed ·
35 open* on the day it was made, not the 65 this task was briefed with. Whichever
is right, a number that cannot be re-derived from anything in this repo does not
belong in it.)

| clip | captured from |
| --- | --- |
| `board-syncs` | `/demo` at a 1040x900 viewport |
| `one-letter` | `/landing-a` at a 1280x1000 viewport — the one exception, argued below |
| `rules-read-the-body` | `/demo/inbox` at a 600x900 viewport |
| `gmail-connects` | hand-recorded, see below |

**`one-letter` is the one clip not captured from the `/demo` family, and the
reason is the fixture rather than the components.** Its subject has to be an
assessment filed AT `assessment`, which has been a stage of its own since
2026-08-12. /demo cannot show that: it holds no `assessment`-status row at all,
and its own Kestrel row sits at `interviewing` with an assessment mail behind
it — which `lib/demo/demoData.ts` documents as stale rather than principled
("these three rows should be filed at it"). Filming /demo would have published
a fixture this repo already knows is wrong. `/landing-a` mounts the SAME
shipped components — the real `PipelineBoard`, `ApplicationRow` and
`ApplicationDetail` — over `components/marketing/showcase.ts`, where Kestrel is
filed at `assessment` with the deadline its mail stated. The rule the /demo
line exists to hold is that no marketing frame carries the owner's real mail or
real employers; every employer in this fixture is invented, so that rule is
kept in full. `/landing-a` is a `noindex` landing candidate: if it is ever
deleted, this scene's anchors match nothing and the capture fails loudly, which
is the intended failure mode.

Every scene now crops at or under 576 CSS px, so `MAX_CROP_W` is not raised
anywhere: the one scene that did raise it (`import-classifies`, 720 CSS px so
the stats row laid out as four cells) is retired. `maxCropW` stays a per-scene
knob, and a scene that raises it still has to say which display width it is
raising it FOR.

The viewports are not arbitrary — `scenes.mjs` says why each one, and changing
them changes what fits in the frame.

### One clip is NOT regenerated by this pipeline

**`gmail-connects` is a hand-made screen recording** of the owner connecting a
real Gmail account to the deployed app. `pnpm footage` cannot re-derive it: it
needs a human with a Google account, and Google's consent screen is not ours to
redraw. Reproducing it in DOM would be inventing an artifact and attributing it
to a real company.

**And it is currently held back entirely** (2026-08-19): Google's consent
screen in the recording names `jobtracker-api-seven.vercel.app`, the host from
before the JobTracker → Applied rename, so no page places it — and since no
page placed it, its ~430 KB of encodes stopped shipping too. `clips.mjs` keeps
the definition and records the return path: rename the Google Cloud OAuth
client, re-record (below), then put `HAND_CAPTURED.id` back at the head of
`CLIPS` and re-run the pipeline.

Without the source, the step is **skipped loudly** and the other two clips
rebuild normally. To include it:

```
FOOTAGE_OAUTH_SOURCE=/path/to/oauth-raw.mov pnpm footage
```

The source is an 11 MB macOS screen recording (3024x1898, ~39s) and is **not
committed** — there is nowhere honest to put an 11 MB binary in this repo. It
lives with the owner. If it is lost, the clip cannot be rebuilt from anything in
here.

**Re-recording it takes:** signing in to the deployed app, Settings → Gmail →
Connect, completing Google's consent, and returning — as one unbroken screen
recording, on a dark theme, at a window size close to 1512pt wide. Then the shot
times and crop rectangles in `remotion/Root.tsx` have to be re-measured against
the new file; they are seconds and pixel rects into that specific recording and
none of them survive a re-record.

**What was cut from it, and why.** All three are whole segments removed. Nothing
inside any frame was composited, relabelled, blurred or re-timed — what Google's
UI says, it says in the clip.

- **3.3s–15.3s — the account chooser and the redirect.** Dead time, and the
  chooser shows a second personal Google account.
- **9s–14.5s (inside that span) — Google's "hasn't verified this app"
  interstitial.** Cut at the owner's explicit instruction: the page states the
  verification status plainly in its Access copy, and the warning is temporary
  state rather than a property of the product.
  **Read this next part before assuming the warning is gone.** The consent
  screen itself carries its own embedded "This app hasn't been verified by
  Google" panel, and it has *not* been painted over — it sits above the crop
  this clip takes. The only ways to remove it are to drop the consent screen
  entirely or to re-record after Google approves the app.
- **17.6s onward — the return, the Settings scroll, and the real dashboard.**
  The tail of the recording is the owner's actual board — 42 filed, 35 open on
  the day it was recorded, every employer name real. **The clip ends on the connection card, not on the
  dashboard**, and it must keep ending there.

The clip is **uncaptioned**, on purpose. A caption of the "here is what you'll
see" kind would claim to depict every screen a visitor meets, which is false
once the interstitial is cut. The footage carries itself: read-only access, one
permission, connected.

Two other things a reader should know about this clip:

- The consent screen names **`jobtracker-api-seven.vercel.app`** — the old
  project name, from before the JobTracker → Applied rename. On a page selling
  "Applied" that reads as a different product. Fixing it means renaming the
  Google Cloud OAuth client and re-recording.
- The email shown, `aesh.03.23@gmail.com`, is already the public contact address
  in the page's own Access copy, so it is not a leak.

## How it works

| file | what it does |
| --- | --- |
| `render.sh` | The one command. Build, serve, capture, compose, gate. |
| `scenes.mjs` | The captured moments: viewport, crop, and the interaction. Also the record of **what was rejected and why** — read it before re-litigating a moment. |
| `capture.mjs` | Drives the app and records frames. |
| `remotion/` | The compositions: crop, re-time, hold, dissolve. `Root.tsx` holds the cut. |
| `render.mjs` | Bundles, renders, encodes both codecs, writes posters and `manifest.json`. |
| `verify.mjs` | Checks the **shipped files** and writes contact sheets. |
| `verify-negative.mjs` | Proves the gates in `verify.mjs` can fail. |
| `metrics.mjs` | The two measurements, shared by both so they cannot drift. |
| `instrument.mjs` | The capture-instrument bake-off. Provenance, not part of the run. |

### Things that were measured, not assumed

Each of these cost a build and an hour. They are here so the next person does not
pay again.

- **Playwright's `deviceScaleFactor` does not reach a CDP screencast.** Frames
  come back at the CSS viewport size whatever `maxWidth` says. Launching with
  `--force-device-scale-factor=2` is what makes them 2x. Re-run
  `instrument.mjs` if you doubt it.
- **A crop wider than ~580 CSS px is unreadable in a 26rem card.** The first
  pass cropped the board at 1180 and every label turned to mush. The ceiling is
  enforced in `capture.mjs`, not remembered.
- **Motion is off under `prefers-reduced-motion`.** `PipelineBoard` and
  `SyncBar` neutralise their animation *props*, so a context that inherited
  `reduce` records a slideshow of end states — a broken-looking app, with no
  error anywhere. `capture.mjs` asserts the media query before recording.
- **Seeking a `<video>` to sample frames returns the PREVIOUS frame.** Checked
  against `board-syncs`, whose counters visibly change: all eight sample points
  came back identical. `verify.mjs` decodes with ffmpeg instead. (The system
  `ffmpeg` on this machine is broken; the pipeline uses the one
  `@remotion/renderer` ships. That build has nearly every filter compiled out —
  no `crop`, no `fps`, no `tile` — so all cropping happens in Remotion.)
- **A mean pixel difference is the wrong statistic for both gates.** It called a
  real change a still image, and — worse — passed a clip whose loop dissolve had
  been deliberately cut off. Both gates count the *share* of the frame that
  moved. The negative control is what caught it.
- **A loop dissolve has to finish one frame before the end.** The last frame
  rendered is `durationInFrames - 1`, so a dissolve ending at the duration stops
  at ~90% and the clip loops out of a half-faded frame.

### The output is not byte-reproducible, and that is correct

`/demo`'s fixtures are dated **relative to today** (`lib/demo/redate.ts`), so a
re-render in November shows November's dates. That is the demo behaving properly.
**Do not put a golden-hash gate on these files.** The capture pins
`timezoneId: "UTC"` so the dates at least do not depend on where the render ran.

### The gates

`verify.mjs` checks each shipped file: that a browser decodes both encodes, that
the last frame matches the first (**loop seam** ≤ 0.1% of the frame), and that
something actually happens (**motion** ≥ 0.15% of the frame changes).

**A tracked clip broke the loop seam, and the fix is in the composition, not
the gate.** `one-letter`'s dissolve joins two camera positions as well as two
moments, which is far more change for an encoder to carry than a dissolve
between two times at one position; VP9 arrived at the final frame still 0.144%
away from it, and the gate correctly called it a visible seam. `Clip.tsx` now
ends the dissolve `LOOP_SETTLE` frames before the duration rather than one, so
the loop point is rendered three times identically and the encoder has
somewhere to converge — 0.000% on the same clip, and unchanged or better on the
other three. **The other three clips' committed encodes predate that change**
(only `one-letter` was re-rendered, to avoid re-dating three clips for
nothing), so the next full `pnpm footage` will move their bytes for that reason
as well as for the demo's relative dates. That is not a regression. **The motion gate cannot see a tracked clip at all**: a camera
move changes the whole frame, so ≥0.15% passes whether or not the product did
anything. What the gate measures for those is that the recording exists; that
the PRODUCT moves in it is the contact sheet's job and the scene header's
claim. That hole is **open and known, not closed**: shutting it needs a
different statistic — change measured inside a STATIONARY sub-window of the
frame, tracked against the camera path — and a negative control of its own,
which is a gate to write rather than a line to add.

**A scene's `forbid` list is now a gate on the camera's whole travel, and it
was positive-controlled.** `one-letter` forbids the board's one closed row
(`Atlas Freight` / "Moving forward with other candidates"): the showcase
fixture carries a rejection deliberately, and it is exactly what this clip must
not be seen filing. Pushing one keyframe 380 px down the worklist made the
capture fail with `forbidden text inside the crop: Atlas Freight @ 234,909` —
so the gate reads the path's bounding box, and the closed group really is
outside it.

`verify-negative.mjs` builds two deliberately broken clips — one with its
dissolve removed, one that is a single held frame — and fails if either gate
stays green. `render.sh` runs it *before* `verify.mjs`, so a green run means the
gates were shown to work on that machine, on that day.

**The numbers are not the check.** `verify.mjs` also writes contact sheets to
`$FOOTAGE_FRAMES/verify/`, every clip sampled at the real 416px card width.
Look at them. A clip can pass every threshold and still be dull, cropped through
a word, or showing the wrong thing.

### Knobs

| variable | default | what for |
| --- | --- | --- |
| `FOOTAGE_PORT` | `3437` | Server port. The run aborts if it is taken. |
| `FOOTAGE_FRAMES` | `apps/web/.footage-frames` | Intermediate frames and contact sheets. Gitignored. |
| `FOOTAGE_ONLY` | — | Comma-separated clip ids, to rebuild a subset. |
| `FOOTAGE_OAUTH_SOURCE` | — | Path to the hand-made OAuth recording. |

Remotion is a **devDependency** and nothing it produces is imported by the app;
the shipped artifacts are video files. Its licence is free for companies of three
people or fewer, and nothing here uses Remotion Lambda or any hosted renderer.
`apps/web/scripts/` is excluded from Vercel deploys by the repo-root
`.vercelignore`, so none of this reaches a build.
