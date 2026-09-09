# Classifier rules governance

What a change to `backend/jobtracker/classifier/rules.py` has to prove before it
lands, what shapes of change are refused, and — stated plainly, because it is
the weakest part — what actually enforces any of it.

## Why this exists

Four commits on `main` already refuse a change by citing issue #10:

| commit | the words |
| --- | --- |
| `6919e63` | "That is the #10 failure mode this had to avoid." |
| `4c68e1a` | "…which would move every verdict in the corpus at once — #10's failure mode." |
| `9e013ff` | "#10 forbids inventing one from three wordings written by the author of the rules." |
| `91838a6` | the same discipline, applied to a counter rather than a pattern |

So the norm is real and is being applied in review. It is being applied **by
issue number**, and an issue number points at a ticket, not at a rule. Someone
who inherits this repository, or an agent asked to fix a misclassification, can
read all four of those commits and still not find the standard they are being
held to.

This document is a transcription of what those four commits actually did. It
invents nothing.

## The failure mode

**A rule edit that fixes the case in front of you by moving verdicts you did
not look at.**

That is the whole of it. The classifier is a scoring walk over regex families,
and almost every pattern is reachable by mail nobody had in mind when it was
written. A patch aimed at one wrong verdict is cheap to write, passes the
suite, and pays for itself by silently misfiling a category the author never
opened.

It has two recurring shapes:

- **Reweighting.** Changing what a match is worth, rather than what matches.
  `4c68e1a` refused exactly this: a reweighting of body matches "would move
  every verdict in the corpus at once and risk misfiling the 41
  acknowledgements". It shipped six narrower twins instead.
- **Invented vocabulary.** Deriving a new pattern family from a handful of
  wordings the author of the rules wrote themselves. `9e013ff` refused to
  invent a withdrawal category "from three wordings written by the author of
  the rules", and left the issue's harder half open rather than guess at it.
  **#768 is the second refusal and the more tempting one**, because the defect
  it declines to fix is severe and measured: third-party lifecycle mail — "the
  candidate you referred was not selected" — scores the reader's category at up
  to 0.95, and through the real additive sync it joins the reader's own live
  card and settles it with nobody asked. The mechanism is proven at board level
  and a 240-message family now grades it. The VOCABULARY is what was refused:
  every third-party wording in the tree is authored, `observed.py` holds none,
  and a survey of published ATS template text found one — JobScore's — third
  party *rejection* sentence in public, with three of six apparent
  reference-request sources turning out to be a single lineage. A pattern family
  keyed on that is n=1, and it would have been graded by a corpus family written
  by the same person. Recorded as DEC-013 with the two conditions that unblock it.

## The rule

### Narrower, never broader

A new pattern must be **strictly narrower than one that already fires**, so it
can only change the score of mail the existing pattern already matched.
`4c68e1a`'s six twins are the model: each is a general form paired with a
noun- or verb-anchored one, "strictly narrower than its partner and can only
fire where the partner already did".

If a change cannot be expressed that way, it is a change to the scoring model
and not a pattern addition, and it needs the corpus evidence in the next
section rather than a review argument.

### Derive; do not copy

A second copy of a vocabulary rots. `9e013ff` needed a set of refutations and
derived them from `PATTERNS[...].negative` through the `_NOISE_NEGATIVES` split
(`classifier/rules.py:1238`, `:1398-1461`) rather than writing them out again,
"so no second copy of the vocabulary can rot". Only the family that genuinely
did not exist — `_RETRACTION`, `:1433` — was authored new, and the commit says
which half is which.

### Name a near-miss that must NOT move

Every rule change ships with at least one case that is close to the target and
must keep its verdict. `6919e63`'s is the sharpest: an acknowledgement from the
**same ATS relay** as the rejection being fixed, asserted to stay
`applied@0.95` with the rejection family scoring `<= 0`. A change that moves
only the case it was aimed at has proved something; a change with no near-miss
control has proved that it works on its own example.

### Measure body-only, against a `None` sender

`4c68e1a` moved its assertion to `AUTO_FILE_GATE` measured against a `None`
sender, because "the old call passed an ATS sender, whose +0.05 bonus lets a
0.80 rung clear 0.85 — a regression from 0.90 would have passed unnoticed". A
sender bonus in the fixture is a floor under the measurement, and it hides the
thing being measured.

### Replay the committed corpora, and name every row that moved

Before and after, on the same tree. Report the rows that changed **and their
gold labels**, not a delta. `4c68e1a`: "no row changed category, and four moved
confidence, every one of them gold-labelled `rejection` and every one upward
(two crossed the gate). Not one acknowledgement moved. The four are named in
`rules.py`."

### Propagate to every port, or say why not, in the commit

`PATTERNS` reaches five tracked surfaces. It is the source in
`backend/jobtracker/classifier/rules.py`; `ml/demo/package_space.py` copies it
into `ml/demo/space/jobtracker/classifier/rules.py`; and it is generated into
`apps/web/lib/demo/rules.json` and `ml/browser/site/rules.json`, the first of
which `apps/web/lib/demo/rulesLayer.ts` reads.

**The Space copy is 182 lines behind `backend/` right now, 65 of them
executable** — measured, not guessed: it is missing `own_text_span`,
`own_text_refutes`, `_RETRACTION` and `_SEMANTIC_REFUTATIONS`, which is the
whole of #417's short-reply work. That is not a defect to file. `package_space.py`
rebuilds the directory wholesale and the Space has been withdrawn since
2026-08-15, and `readme_facts.py`'s vendored-Space invariant is deliberately a
top-level-module comparison rather than a file diff, for a reason worth reading
before anyone "improves" it: a deep comparison would go red on every ordinary
classifier edit and get switched off. So the copy legitimately lags between
repackagings.

It is worth knowing anyway, because it is the honest scale of this section's
subject: **the drift a port accumulates is not visible from the port's source.**

One gate reports it now, for one pair. `scripts/cross_engine_differential.py`
(#427 item 2) runs `rules.py` and `rulesLayer.ts` over the same 135 cases and
reds on a category or a confidence divergence; `e2e-ci.yml` is the only job with
both toolchains, so that is where it runs. It found drift on its first run — the
port has no `reflow_paragraphs`, so a hard-wrapped body scores a bounded gap
differently in the two engines, costing 0.05 of confidence on one fixture and
changing the CATEGORY on another. Both are recorded in the harness, pinned to
their measured values, and still open.

Read its limits with it: it compares two of the five surfaces and it compares
BEHAVIOUR, not pattern lists, so a pattern that drifted without changing any
verdict in the corpus is still invisible. And `e2e-ci.yml` is path-filtered, so
per #864 it cannot be a required check.

**This paragraph described a gap that is now closed, and is corrected rather
than deleted** because the shape of the gap is the lesson. It read: the browser
port cannot be reached, because `ml/browser/site/app.js` is unloadable outside a
browser — a top-level `https:` import, no `export` statements, `document` at
module scope — so covering it means Playwright or a fourth copy of the scorer;
and identical data does not make identical behaviour, because `app.js` matched
every pattern against the RAW body with no `asserted_text` mask, no
quoted-history strip and no reflow, where both compared engines mask first.
`be in touch (soon|shortly|if)` was the confirmed instance: the `if` arm dead in
Python and TypeScript, live in the browser.

#955 closed all of it. The preprocessing moved to `ml/browser/site/preprocess.js`,
`app.js` gained exports and defers its CDN import into `boot()`, the differential
runs the browser as a THIRD arm, and both `rules.json` copies had the `if` arm
removed to match `rules.py`. The differential is 139 cases across three engines
and the browser port diverges on none. What remains true is the general claim
this paragraph was written to make: **the drift a port accumulates is not
visible from the port's source.** Nothing was checking the comment that said
"keep these in step", and it was wrong for as long as nobody looked.

`6919e63` regenerated all of
them and proved the generator faithful first, "by reproducing the committed
rules.json byte-for-byte from the unmodified rules.py". `9e013ff` deliberately
did **not** port its change to `rulesLayer.ts` and said so in the commit,
naming it as real behavioural drift belonging to its own change.

Either is acceptable. Silence is not: a corrected rule that fails to propagate
is the sharper version of this issue's failure mode, because nobody finds out.
That is not hypothetical — #260's anchoring fix left the same unanchored
containment in three other ports until #651.

### A scoring-model change owes a production replay, not only a corpus one

`4c68e1a` and `6919e63` are pattern changes: they move what MATCHES. #523 is the
other kind — it moves what a match is WORTH — and the section above says such a
change "needs the corpus evidence in the next section rather than a review
argument". That is necessary and it was not sufficient, for a reason worth
recording.

The corpus's complement is authored. "249 move and none is wrong" is a claim
about what WRONG mail sits at the shape, and the only wrong mail the corpus
holds at any shape was written by the author of `rules.py`. `observed.py` holds
one non-application wording, a verification code. So a corpus-only argument for
a threshold can show the rung is REACHED by real mail and cannot show it is
SAFE.

The instrument that can is the owner's mailbox, read-only. #523 replayed the 68
distinct wordings of the 96 stored rows through the shipped classifier with and
without the rung, and reported the `(winner, runner-up)` histogram, every row the
rung moves, and the nearest row it does not. That is what made "nothing that must
not file sits at `w>=5, ru<=0`" a measurement rather than an absence of evidence.

**So: a change to the ladder, a gate, or any threshold that decides routing
replays the production mailbox and names every row whose disposition changes.**
It is 96 rows and it takes seconds. A pattern addition does not owe this — its
blast radius is bounded by the pattern.

### A scoring-model change is graded by the SUITE, not by a chosen file set

#523 is the worked example and it is here because the first attempt got it
wrong. The rung was measured against the independent corpus (273 verdicts move,
all correct), against both committed eval corpora, and against the owner's
production board, and every one of those said it was safe. It was then verified
by running the corpus tests, the reach tests and four neighbours — a file set
chosen by the person who wrote the change.

Three tests outside that set were red. `test_ingestion_hole_166.py` classifies a
real `interview` row with NO sender at 5/0 and asserts 0.80, under the gate,
because that is what #260's lookalike anchoring is worth; the rung handed it 0.90
from any sender and the protection became moot. Both of #775's short-circuit
ratchet tests failed too, including the ratchet's own negative control.

The corpus could not see any of it: `harness.classify_all` buckets on CATEGORY,
so a right-category verdict that should have waited for a human scores CORRECT,
and the only non-application wordings in `observed.py` number one.

**So a change to the ladder, a gate, or any threshold that decides routing runs
the whole backend suite before it is believed, and replays the production
mailbox as well as the corpora.** Those are 96 rows and take seconds. A pattern
addition does not owe the production replay — its blast radius is bounded by the
pattern — but it owes the same suite.

### What this document does NOT cover, and how not to route around it

Everything above governs `rules.py` — what matches, and what a match is worth.
It does not govern **disposition**: which messages `cloud/pipeline.py` files,
queues or drops. That is a real boundary and not a loophole, because the two
have different failure modes and different instruments. A pattern edit moves
verdicts nobody looked at; a disposition change moves who gets ASKED, and
`_qualifies_for_hard_row` stands between it and the board either way.

**A change to disposition is governed by the pipeline tests plus
`docs/DECISIONS.md`, and adding vocabulary is a rule change wherever it lives.**
The distinction is what the change READS, never which file it sits in. An
admission arm that composes patterns which already shipped is a disposition
change; one that introduces a new phrase family is a rule change and owes this
document its narrower-than, its named near-miss and its corpus replay — even
when it is written in `pipeline.py` and called a "floor exemption". DEC-010 is
the worked example: #800's withdrawal reaches the queue by composing
`_RETRACTION` (#417) and `references_an_application` (#447), authors no wording,
and records in `DECISIONS.md` that the keyword patch was the rejected
alternative and why.

## What is not evidence

- **Wordings the author of the rules wrote.** A pattern family justified by
  examples from the same person who wrote the pattern is a tautology. Two
  commits refuse it independently. `9e013ff`: #10 "forbids inventing one from
  three wordings written by the author of the rules". `91838a6`, declining to
  add the withdrawal patterns its own measurement had just shown were missing:
  "A pattern for the withdrawal wordings is deliberately NOT in this commit:
  the corpus holds three of them and all three are invented by" the same
  author. Both left a known defect open rather than fix it from a corpus that
  could not judge the fix.
- **A green suite over a corpus that cannot reach the change.** `9e013ff` is
  the model of honesty here: of 18,020 corpus messages, 460 carry a quote
  boundary and **zero** of those have own text under the floor, so the corpus
  could not exercise the new branch at all. The commit says so, and says the
  tests it ships are the only thing that touches it. A green run over
  unreachable code is not coverage and must not be reported as one.
- **A counter that reads zero with no denominator behind it.** `91838a6` pins
  and asserts both denominators first, "because three zeroes with nothing
  behind them is this repository's recurring defect: a grader that graded
  nothing would report a perfect board and keep reporting it." It then proves
  the counter twice by mutation, including a control that must land in a
  *different* bucket.
- **A benchmark that did not move.** The failure mode this document names is a
  narrow patch. A narrow patch is, by construction, benchmark-neutral. "Macro-F1
  is unchanged" is a necessary condition and never a sufficient one.

## What enforces this

Honestly: less than it should.

`backend-ci.yml:233-258` runs two non-regression gates on every push — rules v3
and hybrid v3 deterministic, each `--min-macro-f1 0.95 --tolerance 0.001`. They
fail a rule edit that degrades the benchmark.

**Both are steps in the `test` job, and `test` is not a required context on
`main`.** The three required contexts are:

```
README numbers agree with the code
Scan for secrets
Test data baseline agrees with the tree
```

So a benchmark-degrading rule edit is **detected and still mergeable**. The
gate is a signal in the run log, not a wall.

And the specific failure mode this document exists for — a rule edit that is
narrow but benchmark-neutral — is **neither detected nor stopped by anything**.
No check in any of the workflows asserts that a new pattern is narrower than an
existing one, or requires a named near-miss control. Every rule in the section
above except port parity is enforced by a reader.

Port parity is now enforced for ONE pair and only behaviourally:
`scripts/cross_engine_differential.py` compares `rules.py` against
`rulesLayer.ts` on 135 cases. It does not compare the four `PATTERNS` ports'
pattern lists, it does not reach the Space copy or `ml/browser/site/app.js`, and
being path-filtered it is not a required check. So it narrows this gap rather
than closing it — but "no check compares the ports" is no longer accurate, and
the difference matters to anyone deciding what to build next.

That is the accurate state, and it is written here rather than left implied so
that nobody cites this document as protection it does not provide. Issue #10
tracks closing the gap; #623 tracks the related scope problem in the test-data
gate.

## The smallest check worth building next

From #10's own comment, and it is negative-controllable against a real
historical commit:

1. Parse the ATS domain list out of every port that ships and assert set
   equality, printing the mismatch. A zero-match on any source is a hard
   failure, not a skip — this repository has shipped gates that silently
   measured nothing.
2. Assert the matching predicate is anchored in each, by executing it where the
   language allows and by pattern where it does not. The negative control is
   the literal historical defect: `greenhouse.io.evil.com` must not match.

Scope it to the ports that ship. `README.md:489` records that the Hugging Face
Space and `ml/browser/site/` were withdrawn on 2026-08-15, so two of the four
copies are dormant — which does not weaken the argument for the check, it
sharpens it: four copies of one predicate is the debt this issue names.
