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
`backend/jobtracker/classifier/rules.py`; it is copied verbatim into
`ml/demo/space/jobtracker/classifier/rules.py`; and it is generated into
`apps/web/lib/demo/rules.json` and `ml/browser/site/rules.json`, the first of
which `apps/web/lib/demo/rulesLayer.ts` reads. `6919e63` regenerated all of
them and proved the generator faithful first, "by reproducing the committed
rules.json byte-for-byte from the unmodified rules.py". `9e013ff` deliberately
did **not** port its change to `rulesLayer.ts` and said so in the commit,
naming it as real behavioural drift belonging to its own change.

Either is acceptable. Silence is not: a corrected rule that fails to propagate
is the sharper version of this issue's failure mode, because nobody finds out.
That is not hypothetical — #260's anchoring fix left the same unanchored
containment in three other ports until #651.

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
No check in any of the workflows compares the four `PATTERNS` ports, asserts
that a new pattern is narrower than an existing one, or requires a named
near-miss control. Every rule in the section above is enforced by a reader.

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
