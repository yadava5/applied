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

## DEC-005 — the password-reset result has nowhere to put an error, on purpose

Status: active (2026-09-05)
Claim: `requestPasswordReset` returns one constant notice and its result type
  carries no error field, no status code and no hint about the address. A 429,
  a thrown fetch failure and a successful send are byte-identical to the
  caller.
Why: Supabase's `/auth/v1/recover` enforces "a 60 seconds window before a new
  request is allowed to the same user", and that window **only fires for an
  address that has a user**. So surfacing "you can only request this again in
  51 seconds" confirms the account exists as surely as printing "no such user"
  would. The absence is a type rather than a convention because, in the
  module's own words, discipline in the component is exactly what regresses.
Moved away from: giving the outcome a field that can carry the rate-limit
  result, so the user is told why nothing arrived instead of being shown a
  success notice. This is not a hypothetical reversal — an audit of issue #292
  on 2026-09-05 recommended exactly it, in writing, while the argument against
  it sat in the header of the file being audited. A thorough comment at the
  site was not enough on its own.
Enforced by: apps/web/tests/unit/auth-recovery.test.mjs — drives an unknown
  address, a known one asked twice with a real 429, and a thrown failure, and
  asserts the three outcomes are byte-identical before sweeping the notice for
  "429", "51 seconds", "rate_limit" and "security purposes".
Valid while: the two 429s remain indistinguishable to the client. Supabase
  returns the same status for a project-wide email quota, which is NOT
  user-specific and would be safe to surface, and for the per-user recover
  window, which is not. If a live response is ever measured to separate them,
  the quota half may be surfaced — with the enumeration test extended first,
  since a control that does not know about a branch cannot guard it.
Markers: apps/web/lib/auth/recovery.ts

## DEC-006 — the booklet drift gate stays byte-for-byte, and a red Dependabot booklet PR is finished by hand

Status: active (2026-09-05)
Claim: `booklet/` stays under Dependabot and the System Card drift gate stays a
  byte-for-byte comparison against a rebuild. A booklet dependency pull request
  is therefore EXPECTED to land red, and the design is two actors: Dependabot
  proposes the bump, a human commits the rebuild — on that branch, or on a
  branch that supersedes it. A red booklet pull request is finished or closed
  within its month; the next monthly group supersedes it anyway.
Why: a bundler, plugin or React bump changes the emitted bundle and therefore
  its hashed filename, and Dependabot does not run project build scripts. That
  is not a broken gate, and `.github/dependabot.yml` said so in capitals before
  this entry existed. The cost that IS real is a red nobody reads: this gate is
  the only thing between an edited system card and a stale committed bundle,
  and a check whose red is routine has stopped being a check.
  Both directions are demonstrated rather than asserted. Dependency direction:
  PR #670 red, then green on #781 once the rebuild was committed — one variable
  flipped. Tamper direction: PR #783 changed ONE byte of a committed
  `apps/web/public/system-card` file with `booklet/` untouched, and the gate
  exited 1 naming that file, after its own positive control reported "Guarding
  44 committed files". That second run is what proves the comparison watches
  the committed side and that the artifact-only path trigger fires at all.
Moved away from: four alternatives, each attractive for a different reason.
  (1) A workflow that rebuilds and commits onto the Dependabot branch. It means
  executing freshly bumped third-party code in a job holding a write token, on
  a public repository, to save one five-minute ritual a month. The workflow is
  `permissions: contents: read` deliberately.
  (2) Taking the booklet back out of Dependabot's scope. Killed by the reason
  it went in: a high-severity advisory reached through a transitive dependency
  where GitHub reports NO patched version, so security alerts can never deliver
  the fix and only a routine version bump reaches a tree without the vulnerable
  package. Unwatching recreates exactly the oversight #665 closed.
  (3) Building the card at deploy time instead of committing it. Vercel build
  CPU is the bill, and the committed files are what the git-driven build serves
  directly; this also deletes a reproducibility property nothing else provides.
  (4) Scoping the gate to `booklet/src` so a dependency-only PR skips it. The
  cheapest-looking and the worst: it makes the gate unable to fail in exactly
  the case where the bundle really changed, and — because the workflow also
  watches `apps/web/public/system-card/**` — it would additionally stop the
  gate firing on direct tampering with the committed artifact, which is the
  case PR #783 was run to demonstrate.
Enforced by: .github/workflows/booklet.yml enforces the byte-for-byte half.
  The completion half has no gate and cannot have one here: `booklet-drift` is
  not a required context and cannot become one, because its `paths:` filter
  means it does not run on most pull requests and a required-but-skipped
  context would wedge every unrelated merge. So a red booklet pull request is
  mechanically mergeable, and for that half: nothing enforces this; prose only.
Valid while: the built System Card is committed under `apps/web/public/` and
  served directly. If it is ever built at deploy time, the drift class and this
  entry go with it.
Markers: .github/dependabot.yml, .github/workflows/booklet.yml

## DEC-007 — `ix_emails_review_queue` is kept unused rather than dropped, and the migration that created it is corrected in place

Status: active (2026-09-05)
Claim: the partial index `ix_emails_review_queue` (revision `c8f3a1d64b27`)
  stays in the schema although no product query can use it, and the false
  claims in that revision's own docstring are corrected rather than left as
  history. No new revision drops the index.
Why: the measurement is in #826 and it is one-sided. Every reader was checked
  on a 200k-row corpus and not one implies the index's predicate: the queue
  moved to a `NOT EXISTS` anti-join in #587/#597, the `needs_review` tile has
  no `classified_as` at all, `_reset_review_queue` omits `classified_as`, and
  `linker.py`'s category list excludes `NEEDS_REVIEW`. So the index is dead
  coverage.
  Dropping it is still the worse trade. The cost of keeping it is 856 kB at
  200k rows with 8,000 matching, and negligible at production's ~52 emails —
  a write-time maintenance cost on a table whose write path is a sync nobody
  is waiting on. The cost of dropping it is a new revision executed against
  the production database, which is the estate's highest-risk operation, for a
  saving that is invisible at present scale.
  The second reason is the one that would not have been obvious: the only
  remaining readers of the index are two literals in
  `test_read_path_indexes_postgres.py`, renamed by PR #825 to
  `QUEUE_THE_INDEX_WAS_CUT_FOR` / `TILE_THE_INDEX_WAS_CUT_FOR`. They are the
  demonstration that the shipped index still works, kept deliberately as a
  negative control. Dropping the index deletes that control along with it, and
  a future reader would then have neither the index nor the evidence of what
  it was for.
Moved away from: dropping it in a new revision, which is what "unused index"
  usually warrants and is what the issue lists first. Rejected on the two
  grounds above — a production migration for a saving nobody can measure at
  this scale, and the loss of the only artefact that records the index's
  purpose.
  Also moved away from: leaving the migration's prose alone on the principle
  that a revision which has run is history. That principle is right about the
  revision's SQL and wrong about its docstring, which is not history to the
  next author — it is the file they copy a new revision from. #668 is the
  same lesson: a correction that reached the document and not the source of
  the copy has not landed. The executable body is unchanged and that is
  asserted, not assumed.
Enforced by: backend/tests/test_read_path_indexes_postgres.py enforces the
  half that matters — its two `*_THE_INDEX_WAS_CUT_FOR` literals assert on the
  PLAN, so they fail if the index stops being usable by the queries it was cut
  for, and "kept but dead" cannot silently become "kept and broken".
  The retention itself has no gate and cannot have a useful one here: any
  future revision can drop the index and this file would not notice, because a
  schema object's absence is not something a test of query plans can see once
  the queries no longer use it. For that half: nothing enforces this; prose
  only.
Valid while: production stays at a scale where the index's write-time cost is
  invisible. The condition a reader can check in a minute: if `emails` has
  grown past a few hundred thousand rows for a single user, re-run #826's
  measurement and revisit — the arithmetic that makes dropping it not worth a
  migration is the arithmetic that reverses first.
Markers: backend/alembic/versions/c8f3a1d64b27_read_path_indexes.py, backend/tests/test_read_path_indexes_postgres.py

## DEC-008 — a real sender domain is allowed only where the test keys on that exact domain

Status: active (2026-09-07)
Claim: a fixture may carry a real, routable sender domain only where the test
  exercises code that keys on that exact domain, and only if it names the
  `file:line` it keys on. Everything else uses a reserved domain. The ATS relay
  address already published across seven tracked files is kept, unedited, and
  is not licensed by this carve-out.
Why: the domain is the input production reads.
  `backend/jobtracker/tracking/extractor.py:85` maps that relay's registrable
  domain to a public employer name in the direct-company-domain table, matched
  as a proper subdomain, and the reserved TLDs are not in that table and never
  will be — so a test of the mapping written on a `.test` domain asserts
  nothing at all. That gap is real, and it is the only one: measured on this
  tree, no module carrying the address reaches the table, so the residue is
  retained under the policy's "nothing already published is deleted" section
  rather than by this entry. The carve-out is written for the NEXT fixture, so
  that it is a decision instead of a copy of the last one.
Moved away from: two alternatives, and the first is the obvious tidy-up.
  (1) Substituting a reserved domain everywhere. It removes nothing — the blobs
  stay in history, in code search and in every fork — and in the one place the
  domain is load-bearing it converts a test into a tautology.
  (2) The wide version of this permission: "real domains are fine in tests,
  they identify companies and not people". That is precisely the precedent that
  produced #593. It reasons about harm rather than about whether a test can
  fail, it scopes to nothing, and each new fixture then cites the last one.
Enforced by: scripts/check_test_data.py enforces the visible half — a new
  non-reserved address reds the gate in either direction, so one cannot arrive
  without a deliberate `--write-baseline` commit somebody has to justify. It
  cannot see WHY a domain is there, and no text scan can. For the condition
  this entry actually sets — that the test keys on that exact domain and names
  the file:line — nothing enforces this; prose only.
Valid while: the employer map keys on bare registrable domains and is matched
  with `rules.domain_matches`. If it ever moves to full hostnames, or is
  derived rather than written out, re-read this entry: the reason a reserved
  substitute asserts nothing is that the key is a real registration.
Markers: docs/TEST_DATA_POLICY.md

## DEC-009 — an offer withdrawal is ADMITTED to the queue, not lifted into it

Status: active (2026-09-08)
Claim: a message that scores `other` under `pipeline.REVIEW_FLOOR`, whose own
  asserted text retracts something about the reader's process, and whose named
  employer holds a live `OFFERED` card, is admitted to the human review queue
  by a fourth arm of `collect_review_items`. Its stored confidence STAYS 0.50.
  Nothing about the classifier's score, its category vocabulary, or
  `rules.py` changes, and no new wording is authored anywhere.
Why: the mechanism has to survive the sentence people will use to describe it.
  #800 and #814 both ask for the score to be "lifted into `[0.70, 0.85)`", and
  that wording is wrong twice over. A lift asserts a confidence the classifier
  does not have — 0.50 is the honest answer for a message it has no withdrawal
  class for — and it puts the fix in the scorer, where it would move every
  message the patterns can reach rather than the one the board contradicts.
  What is actually wrong is not the score but WHO GETS ASKED. The precedent is
  pinned: #166's rescue queues a 0.42 untouched, and
  `backend/tests/test_dropped_verdict_is_logged.py` records "Note what does NOT
  change: confidence".
  The predicate consumes NO classifier verdict to decide "contradicts". Its
  operands are the message's own text and a settled card's stage — written at or
  above `AUTO_FILE_GATE`, or by a human. Reading `item.category` through
  `CATEGORY_TO_STATUS` and comparing it to the card would ask the verdict we
  distrust to arbitrate its own doubt.
Moved away from: three alternatives, and the first two are cheap to rebuild.
  (1) A `rescind|withdraw` keyword pattern in `rules.py`. This is the shape
  `docs/CLASSIFIER_RULES_GOVERNANCE.md` refuses, and it has been refused for
  this exact vocabulary twice — `9e013ff` ("#10 forbids inventing one from three
  wordings written by the author of the rules") and `91838a6`, which declined to
  add the withdrawal patterns its own measurement had just shown were missing.
  Per #531 the grading corpus holds no rescission wordings at all, so a pattern
  fitted here would be graded only by fixtures its own author wrote. The
  admission arm sidesteps this by composing two families that already shipped
  and already have controls — `rules._RETRACTION` (#417) and
  `references_an_application` (#447) — and authoring nothing.
  (2) Lowering `REVIEW_FLOOR`, or a score lift. Both move every message in the
  band, and the second is what the two issues literally ask for. See above.
  (3) Keying the withdrawal apart in `review_dedup_key` so the settled filter
  misses it, rather than exempting it. That key is read at four sites and is the
  shared definition of "one decision per conversation per application"; a
  withdrawal names the same application ON PURPOSE, and giving it a different
  identity to dodge a filter would put #454's and #630's guarantees inside this
  change's blast radius to solve a problem that is not about identity.
  Also decided, and pinned either way rather than left to discovery: a
  candidate-authored "I am withdrawing my application" is DROPPED — #447's
  phrase set describes the reader's process as a correspondent speaks of it, and
  the user does not need to be asked to confirm their own decision. A NEGATED
  retraction ("we will not be withdrawing the offer") is ADMITTED, which is a
  known false positive: there is no negation facility in `rules.py` to reuse, so
  excluding it means authoring the wording this entry just refused to author.
  The cost is one review-queue row; nothing files and no status moves.
Enforced by: backend/tests/test_a_withdrawal_reaches_the_queue.py. The gate of
  record is `test_r2_a_withdrawal_reaches_the_queue_through_the_sync`, which
  replays through the sync entrypoint and was red on this branch for BOTH of the
  two drop sites before the fix. `test_r1_the_arm_admits_without_touching_the_score`
  pins the confidence at 0.50, so a later rewrite into the score lift reds rather
  than ships. `test_n1_the_same_text_with_no_live_card_is_still_dropped` is the
  control that separates this from a keyword in a floor costume. All three were
  demonstrated to fail by mutation.
  What is NOT enforced: that a future arm keeps consuming no verdict. Nothing
  can see a `CATEGORY_TO_STATUS` lookup appearing inside the predicate — for
  that half, prose only.
Valid while: `withdrawn` remains unreachable from mail. It is in
  `_TERMINAL_STATUSES` and has no `EmailCategory` to come from and no
  `_STATUS_RANK` entry to advance into (#814), so this change deliberately
  leaves the card reading `offered` with a queue row beside it rather than
  moving a stage it cannot legitimately set. If #814 ships a `WITHDRAWAL`
  category and a status-transition arm, re-read this entry: the admission arm
  becomes the second decision about the same message and one of them should go.
  Also revisit if `contested` is ever widened past `OFFERED` — the scope is
  argued in `applications.employers_with_a_live_offer`, not here.
Markers: backend/jobtracker/cloud/pipeline.py, backend/jobtracker/cloud/applications.py, backend/tests/test_a_withdrawal_reaches_the_queue.py, docs/CLASSIFIER_RULES_GOVERNANCE.md
