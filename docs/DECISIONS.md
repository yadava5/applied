# Decision record

Decisions where the rejected alternative is **attractive** and the reason for
rejecting it is **invisible from the code**. Each entry names what was chosen,
what was chosen against, and what would have to become true for the entry to
stop binding.

## What this file does and does not do

It prevents **relitigation**, not regression. Only a gate prevents regression,
so every entry names its gate — or says, in those words, that nothing enforces
it. Read `Enforced by: nothing enforces this; prose only` as exactly what it
says: the decision holds by agreement and a future change can undo it silently.

`scripts/check_decisions.py` (workflow: `.github/workflows/decisions.yml`)
refuses a record that has gone stale in the three ways a script can see: an
entry missing a field, an `Enforced by:` citing a file that no longer exists,
and a `DEC-nnn` marker in the tree with no entry here or an entry whose marker
is gone from the file it names. It runs on every pull request.

**Three things it cannot see, stated so nobody mistakes this file for cover:**

1. A decision nobody wrote down. This file cannot notice its own gaps.
2. A reversal that edits the code *around* a surviving marker — the marker
   stays true about where it is and becomes false about what it claims.
3. Whether the prose is still accurate. That is what `Valid while:` is for: it
   names the condition a reader can check in one minute, years later, instead
   of taking the entry on trust.

No pull-request checkbox rides on this file. A checkbox cannot fail, and this
repository already has more checklists than it runs.

## Scope

Three tests, all three required, or it does not belong here:

- a competent person would plausibly reverse it;
- the reason is not visible from the code alone;
- the rejected alternative can be **named**.

And one rule that keeps the file from becoming the thing it warns about:
**a decision with a single-subject home goes to that home, not here.** A copy
in two places is the drift engine. The homes:

| subject | document |
| --- | --- |
| what a fixture may contain, and why nothing already published is deleted | `docs/TEST_DATA_POLICY.md` |
| what a classifier rule change must prove | `docs/CLASSIFIER_RULES_GOVERNANCE.md` |
| how a model is allowed to reach production | `docs/ML_PROMOTION_POLICY.md` |
| what the corpus is permitted to claim | `docs/ML_CORPUS_INTEGRITY.md` |
| what the web app is and is not | `docs/WEB_ARCHITECTURE.md` |
| what shipped when, frozen | `docs/timeline.md` |

Entries are **never deleted**. A decision that stops being right gets
`Status: superseded by DEC-nnn`, and its body is frozen as written — the record
of a reversal is the most useful thing in a decision record, and a deleted
entry takes the reasoning with it.

---

## DEC-001 — redacting a published issue body publishes it a second time

Status: active (2026-09-05)
Claim: GitHub issue and pull-request bodies already published are not edited to
  remove material. The residue is documented instead.
Why: an edit does not replace a body, it appends a revision. GitHub serves the
  pre-edit text at `userContentEdits` with `deletedAt: null`, and there is no
  way to remove one — 813 REST paths and all 260 GraphQL mutations were
  enumerated and not one input object accepts a revision. Confirmed empirically
  rather than from the docs: an issue in this repository that was edited to
  redact now reports three revisions, all live. So a redacting edit trades a
  cleaner rendered page for a new machine-readable copy of the exact text being
  removed, and points at it.
Moved away from: editing the bodies, which is the obvious move, costs nothing,
  and looks like the responsible thing to do. It is the reason this entry
  exists — someone will reach for it again.
Enforced by: nothing enforces this; prose only
Valid while: GitHub serves `userContentEdits` and offers no revision delete. If
  a revision-delete mutation ever ships, this decision is void and the scrub
  becomes worth doing.
Markers: docs/TEST_DATA_POLICY.md

## DEC-002 — the hostile-character set is derived from the engine, never listed

Status: active (2026-09-05)
Claim: the code points the mail-text sanitiser neutralises are computed from
  Unicode's `Default_Ignorable_Code_Point` property, less a small set of
  declared exclusions. They are not enumerated by hand.
Why: the hand list held 13 entries and missed U+2060 WORD JOINER, which is
  functionally interchangeable with a code point that *was* covered; a blind
  reviewer defeated the sanitiser with it in one character. Deriving the set
  took it to 3,915 code points across 16 ranges and immediately forced
  dispositions no hand list had named — U+3164 HANGUL FILLER, U+FFA0, U+115F
  and U+1160 are category `Lo` and therefore invisible to any `Cf`-based
  census. The engine's tables are the constraint neither the module nor its
  test controls.
Moved away from: a curated list with a count assertion. The old gate was
  `assert HOSTILE_CODE_POINTS.length === 13`, which meant that **fixing the
  hole reddened the suite** — an inverted gate, and the tell that a list and
  its test were maintained by the same author in lockstep.
Enforced by: apps/web/tests/unit/hostile-text.test.mjs — a 62-row census with a
  universe sweep against `\p{Default_Ignorable_Code_Point}`, shown able to fail
  four ways before it was trusted.
Valid while: the sanitiser's job is invisible characters. A future attack class
  that is *visible* (confusable letters, mixed scripts) is not covered by this
  property and needs its own source of truth, not an addition to this one.
Markers: apps/web/lib/security/hostileText.ts

## DEC-003 — U+061C ARABIC LETTER MARK passes through on purpose

Status: active (2026-09-05)
Claim: the implicit directional marks are not neutralised, even though they are
  default-ignorable and the sanitiser neutralises the rest of that class.
Why: an implicit mark cannot reverse a run — it is not an override. Mail
  clients inject LRM and RLM into legitimate Hebrew and Arabic subject lines,
  so neutralising the class would deface every one of them with a sentinel. The
  residual is real and is written down rather than waved away: an implicit mark
  does meet the module's own definition of the second attack it names, being
  byte-different and pixel-identical.
Moved away from: neutralising everything default-ignorable, which is simpler,
  reads as more secure, and is what a future hardening sweep will propose. The
  cost of that sweep is legible Arabic and Hebrew mail.
Enforced by: apps/web/tests/unit/hostile-text.test.mjs — the census carries
  U+061C as an explicit passthrough row, and deleting that row reds the
  universe sweep by name.
Valid while: mail clients keep emitting LRM/RLM in ordinary subjects. If a
  measurement ever shows the base rate is negligible, the trade flips.
Markers: apps/web/lib/security/hostileText.ts

## DEC-004 — a typed job title outlives a sync that has learned to extract one

Status: active (2026-09-05)
Claim: `position_source` stays, with the inverse of the reason it was created
  for. Not "extraction can never produce a title" but "a title a human typed
  must survive a sync that now can".
Why: the founding premise is dead. The Gmail path fetches `format="full"`, not
  `format=metadata`; `pipeline.role_from_message` reads the subject and then
  the body, and its own docstring says the body half is what makes
  per-application tracking possible when one ATS subject is reused across every
  role a candidate applied to; and the extraction result is written onto auto
  rows. So the column now guards a field that something *is* competing for on
  every sync, which makes it more load-bearing than when it was written, not
  less.
Moved away from: dropping the column "now that extraction works". That reversal
  is attractive precisely because the original justification is gone, and it
  deletes the only thing standing between a working extractor and a person's
  typed answer.
Enforced by: backend/tests/test_user_supplied_role.py
Valid while: the sync writes `position` at all. If extraction is ever removed
  from the filing path, the column is dead weight and this entry is void.
Markers: backend/jobtracker/cloud/applications.py
