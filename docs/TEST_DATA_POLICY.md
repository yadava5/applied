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

It reads tracked files under `backend/tests/`, `backend/jobtracker/`,
`apps/web/tests/` and `ml/` — from `git ls-files`, never a filesystem walk,
because a walk reaches `node_modules`, `.venv*`, `.next` and `__pycache__`, and
a gate that reports hundreds of hits it does not own is a gate that gets turned
off. Product source is in scope on purpose: #593's requisition numbers were not
confined to tests.

`ml/` was added in #615. It had been neither scanned nor named as excluded,
which is a blind spot rather than a decision — and #593's corrected inventory
named `ml/demo/space/jobtracker/classifier/rules.py` explicitly, hours before
the first cut of this gate merged without it. Note that
**`ml/demo/space/jobtracker/` is a generated copy** of `backend/jobtracker/`,
written by `ml/demo/package_space.py` and committed: the same material was
tracked twice and scanned once. A consequence worth knowing before it surprises
you — **repackaging the Space moves the baseline**, because whatever is in
`backend/jobtracker/` gets copied in. That is correct behaviour, not a bug in
the gate; re-record and say so.

For each file it records two things: the **count** of addresses whose domain is
not reserved, by occurrence, and a **digest** — a truncated SHA-256 over the
sorted, lower-cased, de-duplicated set of those addresses.

**Any divergence from the baseline fails, in either direction:** a count up, a
count down, a scanned file that the baseline does not list, a baselined file
that has gone to zero, or a file whose count is unchanged while its digest is
not. That last case is the one the count-only first cut could not see —
replacing one published address with a brand-new one nets to zero (#615).

A tracked file that cannot be read or decoded **fails**. It used to be counted
as zero, so an unreadable file read as clean; a skip that passes is the same
defect as a ratchet that only ratchets one way.

There is **no denylist**, and there will not be one. A list of the exact strings
this gate exists to forbid would republish every one of them, in a new tracked
file, in a public repository. The check is on shape.

### An address that is assembled at run time

Until #647 the gate could see a **literal** and nothing else. Its domain pattern
admitted letters, digits, dot and hyphen, so `f"careers@{domain}"` was not an
address as far as the check was concerned — and neither was `"careers@%s.com"`,
`"careers@" + domain`, nor `"careers@{0}.com".format(...)`. Every interpolation
form this repository actually uses was invisible, which is the worse half of the
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

| written as | sealed suffix | verdict |
| --- | --- | --- |
| `f"careers@{token}.test"` | `.test` | reserved whatever `{token}` is — **silent** |
| `f"hello@acme-{n}hub.example"` | `.example` | the label interpolates, the TLD does not — **silent** |
| `f"careers@{company}.com"` | `.com` | routable — **counted** |
| `f"careers@{n}example.com"` | `.com` | `{n}` may be `not` — **counted** |
| `f"careers@{domain}"` | none | nothing is sealed, nothing can be proved — **counted** |

The three markers are `{...}` (which serves f-string fields, `str.format` fields
and JavaScript template literals alike), `%s`, and `+` concatenation, which is
read by walking the operand chain because its string literal ends at the `@`.

A template is digested by its literal parts, so renaming `{domain}` to `{d}` is
a formatting change and does not move the baseline, for the same reason
re-ordering literals does not.

One consequence to know before it surprises you: **`backend/tests/test_test_data_gate.py`
is now a finding of its own**, because its probe addresses are built as
`f"{local}@{domain}"` and a wholly interpolated domain is exactly the shape that
cannot be proved. That is correct and it is not worked around. Writing the
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

Named so it is a decision and not another blind spot. Outside the four roots
above: `docs/`, `README.md`, `booklet/`, `scripts/`, `api/`, and everything in
`apps/web/` that is not under `tests/`. Those surfaces are covered by the rule
and by review, not by this gate. `apps/web/components/marketing/` and
`apps/web/lib/demo/` are called out under [What is already
clean](#what-is-already-clean) and are deliberately out of scope.

### What the gate does not check

- **It only sees addresses.** A real requisition number, a real subject line or
  a real role title carries no `@` and is invisible to it. The gate measures one
  shape well; the rule above is wider than the gate, on purpose, and review is
  what covers the difference.
- **An assembled address still has edges it cannot reach**, named here so they
  are a decision rather than another blind spot. An interpolated *local* part
  over a literal routable domain — `f"{i}@corp.com"` — is invisible: the run
  after the `@` holds no marker, and the `}` in front of it stops the literal
  pattern too. Three sites in the tree, one of which is an iCalendar `UID:`
  field and not an address at all, which is why closing it is a judgement about
  false positives and not a free widening. A domain concatenated out of literals
  only is invisible, and so is anything assembled through a call — `"@".join`, a
  format string held in a constant. A text scan ends where dataflow begins.
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
