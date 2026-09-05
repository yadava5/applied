# Test data policy

What a fixture in this repository is allowed to contain, why the material that
is already here is staying, and what enforces the difference.

This repository is **public**. Fixture bodies, docstrings, inline comments,
commit messages, PR bodies and issue bodies are all published surfaces — GitHub
serves every one of them, code search indexes them, and forks copy them. The
distinction between "test data" and "prose about test data" does not exist from
the outside.

## Why this exists

Issue #593 found metadata transcribed from the owner's real mailbox spread
across the repository: an ATS relay sender address in seven tracked files,
verbatim subject lines, real requisition numbers, real role titles, production
row ids, and the owner's own first name inside fixture bodies. Six public issues
carry the same material in their bodies or comments.

Nothing there is a credential and nothing identifies a third party, so it is not
an incident. It is job-search information about one identifiable person,
published, and it accumulated **by precedent rather than by decision** — each
new test copied the shape of the last one, because there was no rule to cite.

That is the gap this document closes. It is not a cleanup.

## The rule

Anything published from this repository that carries a sender address, an
employer, a requisition number or a role title uses **invented** particulars:

| you are writing | use |
| --- | --- |
| a sender address | a domain that cannot route — see [Reserved domains](#reserved-domains) |
| an employer | an invented company. Northwind Systems, Halberd, Ironvale Robotics |
| a requisition number | an invented one, in a shape no real ATS issues |
| a role title | an invented or generic one |
| a person's name | a placeholder, or a parameter — `{display}`, `{role}` |

The rule covers **fixtures, docstrings, comments, commit messages, PR bodies and
issue bodies**, not fixtures alone. Scoping it to fixtures would have permitted
the most recent leak exactly as it happened: on PR #587 the fixture bodies were
correctly sanitised to `.test` senders and the real relay address went in through
the module **docstring** above them, where it sits on `main` today.

### Reserved domains

The allowlist is not a matter of taste, which is why it is closed to argument.
RFC 2606 §2 reserves the `.test`, `.example`, `.invalid` and `.localhost`
top-level domains; §3 reserves `example.com`, `example.net` and `example.org`
**and everything under them**, so `email.careers.example.com` is as un-routable
as the bare name; RFC 6761 §6.3 makes `.localhost` un-routable by definition.
Nothing in that set can ever reach a real mailbox, and that is the only property
being asserted.

A domain that merely *looks* invented is not in the set. `acme.com`,
`northwind.com` and `initech.com` are real registrations owned by somebody else,
and a fixture that mails one of them is describing a real destination.

### The shape to copy

`backend/tests/test_dismissed_card_does_not_settle_its_mail.py`. Three invented
employers — Northwind Systems, Halberd, Ironvale Robotics — with senders at
`careers@halberd.test`, `careers@ironvale.example.test` and
`donotreply@email.careers.example.test`. The last one is worth looking at: it
preserves the *structure* of a real ATS relay hostname, which is what the
sender-anchoring code reads, while the labels that identify anyone are invented.

### The document is not exempt

**Any address spelled out in this file sits on a domain that cannot route, and a
routable domain is named as a domain rather than written as an address.** That
is one sentence, it is the same rule as everything above, and it applies here
for the reason it applies anywhere: there is no argument for the file that
states the rule being the file that breaks it.

It has a history worth keeping. Until #623 the gate read four roots and this
document was outside all of them, so it had accumulated eight address-shaped
illustrations on routable suffixes — the ones in [An address that is assembled
at run time](#an-address-that-is-assembled-at-run-time), now written as bare
domains, which is what they were always about. The obvious alternative was to
exempt this path in the gate, and it was rejected: an exemption is not scoped to
the text that motivated it, so it would have covered every address added to this
file afterwards, for any reason, by anybody — a rule with a hole in it exactly
where the rule is written down, which is this repository's recurring defect
wearing a hat.

The convention is not new, either.
`apps/web/tests/unit/no-real-employer-in-shipped-fixtures.test.mjs` carries the
same note about its own prose — "it names domains, never addresses" — and
predates this section by an issue.

Scoring zero is also **stronger** than a baseline entry would have been. This
file now appears nowhere in `scripts/test_data_baseline.json`, so the next
address added to it, in any section, reds the gate as a new file. A baselined
count would have had to be re-recorded to change; an exemption would have said
nothing at all.

Two places where the rule bites and the answer is *record*, not rewrite:
`scripts/check_test_data.py`'s own examples stay verbatim, because one of them
quotes the open-redirect fixture `test_gmail_oauth_return_host.py` exists to
refuse and an example that does not match what it documents is worth less than a
baseline line; and everything in [The baseline is a
ratchet](#the-baseline-is-a-ratchet-not-a-backlog) still holds for material that
carries a provenance claim. The rule governs **writing**. The baseline records
**what is already written**. No file is outside either.

## When the real message is the only evidence

Several modules here are graded against wordings that a classifier has to read
correctly and that nobody would have invented — the shape of an ATS
confirmation, a rejection that opens like an interview invitation, a follow-up
relayed by the employer's robot rather than sent by the reader. That evidence is
real and it is the point of the test.

Keep the **shape**. Replace the **particulars**. Then say which is which:

> The wording of this body is real — an ATS confirmation, transcribed for the
> pattern the classifier must read. The employer, the sender address and the
> requisition number are invented.

Two sentences in the docstring, and the provenance claim stays true while the
identifying detail never ships. A test that quietly swaps real wording for
invented wording *and leaves the docstring claiming it is real* is worse than
either — it is a false provenance claim, which is this repository's named
recurring defect.

## The baseline is a ratchet, not a backlog

`scripts/test_data_baseline.json` lists the tracked files that already contain
addresses on non-reserved domains, with a count and a digest for each. **It is
not a to-do list, and working it down is not an improvement.** (No count is
written here on purpose: a number in prose drifts silently and nothing gates
this file. The baseline is its own authority.)

Three reasons, and the first is the one that settles it:

1. **A forward delete removes nothing.** The blobs stay in git history, in
   GitHub's blob store, in code search and in every fork. This is the same
   reasoning that closed PR #285 and re-cut it as a squashed branch rather than
   patching forward. A scrub buys the appearance of a fix and none of a fix.
2. **Several of these modules make provenance claims.** They say, in their own
   docstrings, that they are graded against real ATS wordings — and they are.
   Rewriting the values while leaving the prose ships a claim that is false;
   rewriting the prose too deletes the reason the test is trusted.
3. **A partial scrub is worse than none.** The same requisition numbers sit in
   product source (`backend/jobtracker/cloud/pipeline.py`,
   `backend/jobtracker/classifier/rules.py`) as well as in tests. Sanitising the
   tests while the values remain in the code they test leaves the material
   published and the repository looking as though the question was handled.

Whether to scrub properly — a history rewrite, which breaks every open PR and
cannot un-index what is already served — is the owner's decision and is
deliberately still open. Until it is made, **nothing already published is
deleted**, and this section exists so that a future reader who notices the
baseline does not helpfully "fix" it.

**The issue-edit half of that sentence is now decided, against — DEC-001.** An
edit to a published issue body does not replace it. GitHub appends a revision
and serves the pre-edit text at `userContentEdits` with `deletedAt: null`, and
no REST path or GraphQL mutation can remove one; an issue in this repository
that was edited to redact now reports three live revisions. So redacting an
issue buys a cleaner rendered page and mints a new machine-readable copy of the
exact text being removed. Do not edit them. The reasoning, and the condition
that would void it, are in `docs/DECISIONS.md`.

### The ratchet turns both ways

Until #615 a count going DOWN was printed and forgiven. That was slack with a
mechanism: remove three addresses this month, add three different ones next
month, green both times, and nothing in the repository records that either
happened. Divergence in **either** direction now fails.

Be precise about what that buys, because the gate does not do what a careless
reading of this paragraph suggests. It does **not** prevent a removal, and a
pull request whose only change lowers the baseline is **green** — because once
the baseline is re-recorded it matches the tree again, which is the whole point.
What the gate guarantees is narrower and is enough: no change to this material
can reach `main` without a commit that re-records the baseline. The audit is
that commit and its message, not the check. The check is what makes the commit
impossible to skip.

So: removal is allowed, it is not routine, and it is never silent. State in the
commit body which files moved and why, and read the three reasons above first.

Record it the way `docs/ML_PROMOTION_POLICY.md` records Cycle H's 0.9583: a
number that is correct as it stands and must not be corrected.

## What is already clean

Worth stating so nobody audits it a second time:

- `backend/data/evaluation/classifier_eval_v*.jsonl` — the tracked evaluation
  sets are synthetic throughout. Invented employers: `northstar.ai`,
  `acme.com`, `brightlane.dev`.
- `backend/data/evaluation/real_labeling_batch_*.csv` — real, and gitignored at
  `.gitignore:72`. It has never been tracked.
- `apps/web/components/marketing/heldMail.ts`,
  `apps/web/components/marketing/verdictEmailData.ts` and
  `apps/web/lib/demo/sampleInbox.ts` contain the owner's first name **on
  purpose**. That is product copy in a demo the owner ships under his own name,
  not a fixture leak, and it is not in this gate's scope. Do not conflate the
  two.

Two of those entries came **into** the gate's scope in #623 and are now counted
and baselined, which is not the same as being cleared:

- the evaluation corpora contribute 170 of the addresses the baseline records.
  "Synthetic" is a claim about the material — no personal address, no real
  employer — and not about the domains: several of the invented-looking
  employers are live registrations that accept mail today. The ATS *vendor*
  domains among them are load-bearing, because `ATS_DOMAINS` in
  `classifier/rules.py` matches on them by name, and the placeholders are not.
  Whether either should change is reserved to the owner in #623 and #593, and
  nothing here decides it.
- the demo data under `apps/web/lib/demo/` and the marketing components are
  rendered to every visitor and are read by this gate for the first time. Same
  reservation: recorded, not endorsed.

**The baseline is a ratchet, not a certificate.** Recording an address means
somebody will see it move. It does not say it is fine.

## The gate

`scripts/check_test_data.py`, run by `test-data.yml` — its own workflow, whose
only job is named **`Test data baseline agrees with the tree`**. It needs no
database, no torch and no network — it is stdlib Python and one `git ls-files`,
and it answers in about six seconds.

It has moved twice, and both moves were forced by the same property.

It was a *step* inside the `test` job until #615, which was two problems. `test`
is the ~25-minute suite job, so the fast answer waited on the slow one; and
`test` is not a required context, so a red gate left the pull request
`MERGEABLE`. Requiring `test` would have fixed the second by making the first
worse. Hence a job of its own, which can be required on its own.

It was then a job inside `backend-ci.yml` until #617, and that home stopped
being correct the moment the owner made the check **required**. `backend-ci.yml`
is path-filtered to `backend/**` and a short list of siblings, so a pull request
touching none of those paths — a documentation change, or one confined to
`apps/web/components/**` — never produces this context at all. A required
context that is never produced neither passes nor fails: it sits at *Expected —
waiting for status*, and nobody but an admin can merge. That is not a strict
gate, it is a wedge, and it is the same "check that cannot fire" defect the path
filters in `backend-ci.yml` are commented against.

Adding the two scan roots that live outside `backend/` to that workflow's
filters (`apps/web/tests/**`, `ml/**`) was the correct patch while the check was
advisory: it made the gate fire on the trees it reads. It could not fix the
wedge, because the wedge is about the paths the gate does **not** read — the
gate has to run on a pull request that changes nothing it scans, in order to say
so. Only an unfiltered workflow does that. The cost argument the old filters
carried also inverts here: `ml/**` was firing the entire ~25-minute backend
suite, two Postgres services included, so that a six-second stdlib script could
read a model blob's directory. Splitting it removes that too.

> **Required, and matched by name.** `required_status_checks.contexts` names
> **`Test data baseline agrees with the tree`** — the job's `name:`, not its
> file or its job id. Moving the job between workflow files is therefore
> invisible to branch protection, which is what made the #617 split safe; but
> *renaming* the job silently un-requires the gate, because protection keeps
> waiting for a context nothing produces and the check that replaced it is
> advisory without anyone having decided that. The other two required contexts,
> `README numbers agree with the code` and `Scan for secrets`, are unfiltered
> for the same reason this one now is.

```
python3 scripts/check_test_data.py                   # check (what CI runs)
python3 scripts/check_test_data.py --write-baseline  # deliberately re-record
```

It reads **every tracked file** — from `git ls-files`, never a filesystem walk,
because a walk reaches `node_modules`, `.venv*`, `.next` and `__pycache__`, and
a gate that reports hundreds of hits it does not own is a gate that gets turned
off. Product source is in scope on purpose: #593's requisition numbers were not
confined to tests.

Every tracked file **minus a list of exclusions, which is currently empty** —
`EXCLUDED` in the script. Until #623 it was the other way round: four scan roots,
and the rest of a public repository outside the gate by construction. An
allowlist's blind spot is an *absence*, and nothing enumerated what those four
roots left out; the measurement, when somebody finally took it, was 239
non-reserved addresses across 24 tracked files — the demo data the product
renders to every visitor, the evaluation corpora, the built system-card bundle,
the script itself and this document. The roots had already been patched twice
for the same defect ("a root the gate does not read"), which is what makes the
direction wrong rather than the list too short. Inverted, the default is scanned
and every exception is a line somebody had to write a reason on.

Two consequences worth knowing before they surprise you.
**`ml/demo/space/jobtracker/` is a generated copy** of `backend/jobtracker/`
(`ml/demo/package_space.py`), so the same material is tracked twice and counted
twice, and repackaging the Space moves the baseline. And **rebuilding the
system-card bundle moves it in the noisiest way this gate has**: those files are
named by content hash, so a rebuild reads as a new file *plus* a cleared one —
see "It reports a rename badly" below — and the minified CSS bundle's
`}@font-face{` runs match the template reader eleven times as addresses they are
not. Over-counting is the safe direction, so they are recorded rather than
excluded; the sibling `.js` bundle holds five that are real.

### A file that is not text

Scanning everything means meeting the first PNG, and on this tree that PNG made
the widened gate refuse the whole run — correctly, because a file the gate
cannot read is not a file it can call clean. So the file is sniffed:

| the file | what happens |
| --- | --- |
| its bytes decode as UTF-8 | scanned, and its findings are baselined |
| its bytes do not decode | **skipped, and the skip is baselined** |
| it cannot be read at all | the run **fails** — a broken checkout, or a tracked file that is gone |

The sniff is on **content**, never on an extension. An extension allowlist is a
second allowlist with a second invisible blind spot, which is the defect the
paragraphs above are about. It is not git's "a NUL byte in the first 8000"
heuristic either: measured on this tree, 54 tracked files fail to decode and
every one of them is a font, an image or a video, while the one tracked *text*
file that carries a NUL — `apps/web/lib/feedback/coalesce.ts`, whose field
delimiter is one — decodes fine. The NUL rule would have dropped product source.

A skipped file is **recorded** in the baseline rather than dropped from it, so
that "nobody read this one" can never print like "this one is clean", and so
that adding a binary file is a line in a diff instead of a silent widening of
what nobody looks at.

And `--write-baseline` **refuses to move a file from scanned to skipped**. That
is the door this sniff opens and the one worth guarding: corrupt one byte of a
module holding fifty addresses and it stops decoding, and a re-record would
launder those fifty findings into a skip, leaving every later run green on a
file nobody read. The write path names the file and refuses. Restore it first.

For each file it records two things: the **count** of addresses whose domain is
not reserved, by occurrence, and a **digest** — a truncated SHA-256 over the
sorted, lower-cased, de-duplicated set of those addresses.

**Any divergence from the baseline fails, in either direction:** a count up, a
count down, a scanned file that the baseline does not list, a baselined file
that has gone to zero, a file whose count is unchanged while its digest is not,
or a change to the set of files that were skipped rather than read. The digest
case is the one the count-only first cut could not see — replacing one published
address with a brand-new one nets to zero (#615).

A tracked file that cannot be **read** fails. One that cannot be **decoded** is
skipped and recorded as skipped. Neither is ever counted as zero: it used to be,
so a file nobody could read passed as clean, and a skip that passes silently is
the same defect as a ratchet that only ratchets one way.

There is **no denylist**, and there will not be one. A list of the exact strings
this gate exists to forbid would republish every one of them, in a new tracked
file, in a public repository. The check is on shape.

### An address that is assembled at run time

Until #647 the gate could see a **literal** and nothing else. Its domain pattern
admitted letters, digits, dot and hyphen, so a sender whose domain was assembled
at run time was not an address as far as the check was concerned: not an
f-string field (`{domain}`), not `%s`, not `+` concatenation, not a `str.format`
field. Every interpolation form this repository actually uses was invisible,
which is the worse half of the
finding: writing a sender as an f-string is the *natural* way to write one, and
most of this suite does, so a fixture author got a green gate unconditionally.
It was hiding senders on two real companies' own domains in
`backend/tests/test_gmail_oauth_cloud.py`, assembled by passing the domain in
from a call site — and the call site is a plain string with no `@` in it, so no
address scanner will ever find it there either.

The fix is **not** to let `{`, `}` and `%` into the domain pattern. That matches
a "domain" of `{token}.test` and then asks whether that string is reserved,
which is reading a template as though it were a name. The question is whether
the address could **resolve** somewhere, and for a template that is a question
about the part of the domain no interpolation can change — the **sealed
suffix**, everything after the last interpolation from its first literal dot:

Only the **domain** decides; the local part plays no part in this judgement. So
the domains below are written without one — which is also how this document
obeys its own rule, see [The document is not
exempt](#the-document-is-not-exempt).

| the domain, as written | sealed suffix | verdict |
| --- | --- | --- |
| `{token}.test` | `.test` | reserved whatever `{token}` is — **silent** |
| `acme-{n}hub.example` | `.example` | the label interpolates, the TLD does not — **silent** |
| `{company}.com` | `.com` | routable — **counted** |
| `{n}example.com` | `.com` | `{n}` may be `not` — **counted** |
| `{domain}` | none | nothing is sealed, nothing can be proved — **counted** |

The three markers are `{...}` (which serves f-string fields, `str.format` fields
and JavaScript template literals alike), `%s`, and `+` concatenation, which is
read by walking the operand chain because its string literal ends at the `@`.

A template is digested by its literal parts, so renaming `{domain}` to `{d}` is
a formatting change and does not move the baseline, for the same reason
re-ordering literals does not.

One consequence to know before it surprises you: **`backend/tests/test_test_data_gate.py`
is now a finding of its own**, because its probe addresses are assembled at run
time from a local part and a wholly interpolated domain (`{domain}`), which is
exactly the shape that cannot be proved. That is correct and it is not worked
around. Writing the
gate's own probes in a construction the gate cannot see is the defect #647 is
about.

### Why a digest is allowed where a literal is not

The obvious objection to storing a hash of the material is that it is still
derived from the material. It is, and the distinction is worth writing down
rather than assuming.

A denylist is **publication**: it hands the exact strings to every reader,
every fork and every code-search index, in a file that did not previously
contain them. A digest gives a reader who *already holds a candidate string*
the ability to confirm it, and gives a reader who does not hold one nothing at
all. It is a confirmation oracle, not a disclosure, and it is strictly weaker
than the thing being avoided.

Be honest about the limit: a file with a single address has a digest over a
single-element set, so anyone who guesses that address can check the guess. No
salt fixes this — a salt committed next to the digest is not a salt, and a salt
kept outside the repository makes the baseline irreproducible by CI, which is
the one property it must have. The trade is accepted deliberately: confirming a
string you already possess is not the harm this policy exists to prevent, and
the alternative is a gate that cannot see a swap.

### What is not scanned

Named so it is a decision and not another blind spot. **Three things, and the
list is meant to stay this short:**

- Anything named in `EXCLUDED` in `scripts/check_test_data.py`, which is
  **currently empty**. That is the measured answer rather than an omission:
  every tracked file in this repository either scans clean, is recorded in the
  baseline, or does not decode and is recorded as skipped. Nothing needed a
  line — not the lockfiles, not the generated API schema, not the built bundles.
- Files whose bytes are not UTF-8 — see [A file that is not
  text](#a-file-that-is-not-text). Skipped, and *recorded* as skipped.
- Untracked files. `git ls-files` reads the index, so `node_modules/`, `.next/`
  and a scratch file nobody staged are out; a staged file is in.

Everything else is read: `docs/` and this document, `README.md`, `booklet/`,
`scripts/`, `api/`, the whole of `apps/web/` rather than only its `tests/`, the
evaluation corpora under `backend/data/`, and the built system-card bundle. That
was #623's point — the surfaces most likely to be read by a stranger, the
landing page and the demo fixtures and the docs, were the ones with no scan over
them at all.

### What the gate does not check

- **It only sees addresses.** A real requisition number, a real subject line or
  a real role title carries no `@` and is invisible to it. The gate measures one
  shape well; the rule above is wider than the gate, on purpose, and review is
  what covers the difference.
- **An interpolated local part over a literal domain is read now** (#619). A
  template whose local part interpolates over a spelled-out domain used to be
  invisible from both sides at once: the run after the `@` holds no marker, so
  the template reader did not fire, and the `}` in front of it stopped the
  literal one. The domain is the part that routes, so this was the half worth
  having.

  It is judged on that literal domain exactly as a written-out address is, so
  the same shape over `halberd.test` stays silent and over a routable domain
  counts. Written as domains here rather than as addresses, per the rule this
  document sets for itself in [The document is not
  exempt](#the-document-is-not-exempt) — the shape is the point and spelling a
  routable one out would put this file in the baseline it governs.

  Two **non-addresses** are now recorded rather than avoided, and that is a
  decision rather than an oversight: `corpus/mail.py`'s iCalendar `UID:` field
  on `google.com`, and `conftest.py`'s synthetic Message-ID on `test.com`.
  Neither is a sender. The baseline is a ledger of address-shaped runs, not an
  accusation — no text scan can tell those shapes from a sender, and a *run*
  that scored zero could never red on an edit. One declared line buys a digest
  that moves when the file's addresses do.
- **An assembled address still has edges it cannot reach**, named here so they
  are a decision rather than another blind spot. A domain concatenated out of
  literals only is invisible, and so is anything assembled through a call —
  `"@".join`, a format string held in a constant. A text scan ends where
  dataflow begins.
- **It sees the set, not the string.** Since #615 a same-count swap fails,
  because the digest is over the set. But the gate still cannot tell a *better*
  address from a worse one — replacing one non-reserved address with a different
  non-reserved address reds exactly as loudly as replacing it with nothing, and
  the reader has to look at the diff to know which happened. That is deliberate:
  the gate's job is to make the change visible, not to judge it.
- **It reads files.** Commit messages, PR bodies and issue bodies are in the
  rule's scope and out of the gate's reach entirely. Six public issues already
  carry this material; nothing mechanical will catch the seventh.
- **It reports a rename badly.** Moving a baselined file shows as a new file
  *and* a cleared one, and the headline says "new sender addresses" when nothing
  was added. Read the two lines together before believing it.
- **It does not read history.** It measures the working tree. Everything in
  section [The baseline is a ratchet](#the-baseline-is-a-ratchet-not-a-backlog)
  applies.

What it *does* cover, and this is the part worth knowing: it is a whole-file
text scan, so **docstrings and comments are checked**, not just string literals.
That is the leak #593 predicted and the one that had already landed.

### Proving it can fail

This repository's named recurring defect is a check that cannot fail, and it has
shipped four rounds of it. `backend/tests/test_test_data_gate.py` builds a
throwaway git tree and asserts every claim the gate makes, each of which is a
separate code path:

| case | verdict |
| --- | --- |
| a count going up in a baselined file | red |
| a brand-new file with a hit | red |
| a same-count swap — the set moved, the total did not | red |
| a count going down | red |
| a baselined file going to zero | red |
| a tracked file that cannot be decoded | red, in check *and* in `--write-baseline` |
| a pre-#615 counts-only baseline | refused, not half-read |
| re-recording after a removal | green — the escape hatch has to work |
| the same addresses reordered, re-cased or duplicated | green |
| an address on a reserved domain | green |
| an address assembled at run time on a routable domain | red |
| the same assembly with a reserved literal suffix | green |
| an untracked file | not scanned |
| an address under `docs/`, which no scan root ever covered | red |
| the same file, same path, with a reserved address | green |
| a tracked file whose bytes are not UTF-8 | skipped, and red until the skip is recorded |
| a file that WAS scanned and stops decoding | `--write-baseline` refuses to record it |
| a path named in `EXCLUDED` | not scanned |

The green rows are not padding. A gate that reddened on `careers@halberd.test`
would punish the shape this document tells you to write. It nearly did: review
found that the first cut matched `example.com` exactly and so flagged
`donotreply@email.careers.example.com`, the `.com` analogue of the address cited
above as the shape to copy. Subdomain cases are in the test now. The
reorder-stays-green row is the control on the swap row — without it, the swap
red could have come from the bytes changing rather than from the set changing.

The test module lives inside a scanned root, so every probe address in it is
assembled at run time from fragments split at the `@`. It asserts that about
itself, and it asserts that the baseline file never contains any of them.
