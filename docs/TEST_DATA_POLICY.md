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
top-level domains; §3 reserves `example.com`, `example.net` and `example.org`;
RFC 6761 §6.3 makes `.localhost` un-routable by definition. Nothing in that set
can ever reach a real mailbox, and that is the only property being asserted.

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

`scripts/test_data_baseline.json` lists 83 tracked files that already contain
addresses on non-reserved domains. **It is not a to-do list, and working it down
is not an improvement.**

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

Whether to scrub properly — history rewrite plus issue edits, which breaks every
open PR and cannot un-index what is already served — is the owner's decision and
is deliberately still open. Until it is made, **nothing already published is
deleted**, and this section exists so that a future reader who notices the
baseline does not helpfully "fix" it.

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

`scripts/check_test_data.py`, wired into `backend-ci.yml` as a required step. It
needs no database, no torch and no network — it is stdlib Python and one
`git ls-files`.

```
python3 scripts/check_test_data.py                  # check (what CI runs)
python3 scripts/check_test_data.py --write-baseline  # deliberately re-record
```

It reads tracked files under `backend/tests/`, `backend/jobtracker/` and
`apps/web/tests/` — from `git ls-files`, never a filesystem walk, because a walk
reaches `node_modules`, `.venv*`, `.next` and `__pycache__`, and a gate that
reports hundreds of hits it does not own is a gate that gets turned off. Product
source is in scope on purpose: #593's requisition numbers were not confined to
tests.

It counts, per file, the addresses whose domain is not reserved. **A count going
up fails. A scanned file appearing that is not in the baseline fails.** A count
going down does not fail; it is printed, and lowering the recorded number is a
deliberate act with a reason in the commit body.

There is **no denylist**, and there will not be one. A list of the exact strings
this gate exists to forbid would republish every one of them, in a new tracked
file, in a public repository. The check is on shape.

### What the gate does not check

- **It counts.** Swapping one non-reserved address for another, or sanitising
  one file while adding an address to the same file, nets to zero and is
  invisible to it. So is a real requisition number, a real subject line or a
  real role title — those carry no `@`. The gate measures one shape well; the
  rule above is wider than the gate, on purpose, and review is what covers the
  difference.
- **It reads files.** Commit messages, PR bodies and issue bodies are in the
  rule's scope and out of the gate's reach entirely. Six public issues already
  carry this material; nothing mechanical will catch the seventh.
- **It does not read history.** It measures the working tree. Everything in
  section [The baseline is a ratchet](#the-baseline-is-a-ratchet-not-a-backlog)
  applies.

What it *does* cover, and this is the part worth knowing: it is a whole-file
text scan, so **docstrings and comments are checked**, not just string literals.
That is the leak #593 predicted and the one that had already landed.

### Proving it can fail

This repository's named recurring defect is a check that cannot fail, and it has
shipped four rounds of it. `backend/tests/test_test_data_gate.py` builds a
throwaway git tree and asserts three things, which are the three the gate
claims: a count going up in a baselined file reds, a brand-new file with a hit
reds, and an address on a reserved domain stays green. That last case is not
padding — a gate that reddened on `careers@halberd.test` would punish the shape
this document tells you to write.
