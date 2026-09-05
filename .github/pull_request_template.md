<!--
Prompts, not a checklist. Delete every heading that does not apply — an empty
section is worse than no section. The house style is that a PR body is the
evidence, so prefer a measured number or a `file:line` over an adjective.
-->

## What changed and why

## How it was verified

<!--
Name the command and the result, not the intent. If a suite was not run, say
which and why. A gate that ships new must be shown to FAIL before it is shown
to pass.
-->

## If this touches `backend/jobtracker/classifier/rules.py` or a port of it

Read `docs/CLASSIFIER_RULES_GOVERNANCE.md` first. Issue #10 is the standard and
that document is its transcription. This section is what it asks for:

- **Narrower, not broader.** Which existing pattern does the new one sit
  strictly inside, so it can only fire where that one already did? If it cannot
  be put that way, say so — it is a scoring change and needs corpus evidence.
- **The near-miss that must NOT move.** Name the case closest to the target that
  keeps its verdict, and give the before and after.
- **Corpus replay.** Before and after on the same tree. Name every row that
  moved and its gold label. "Macro-F1 unchanged" is necessary, never sufficient:
  a narrow patch is benchmark-neutral by construction.
- **Propagation.** `PATTERNS` reaches `ml/demo/space/jobtracker/classifier/rules.py`,
  `apps/web/lib/demo/rules.json` and `ml/browser/site/rules.json`. Say which
  were regenerated, or say why not — but say. A corrected rule that fails to
  propagate is #10's sharpest form, because nobody finds out.

## Anything that got worse, or that this deliberately leaves open
