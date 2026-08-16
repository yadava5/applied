# ML Promotion Policy

When a learned layer is allowed to classify real user mail, what it has to beat
first, and what puts it back.

This exists because "the app learns from your corrections" is currently a
description of a *training* path, not of a serving one, and because the two
gates in `backend-ci.yml` measure neither. Both committed baselines read 0.9791
because both runs are the deterministic path: `--mode rules`, and `--mode hybrid
--hybrid-profile deterministic`, which calls `set_lite_mode(True)` and blanks the
embedding store. Nothing in CI has ever scored a model.

## Status today — 2026-08-11

Measured on the committed 96-example v3 set
(`backend/data/evaluation/classifier_eval_v3.jsonl`,
SHA-256 `0aa053536573cd733293fa6a054076a5f78b5c01ebc559e7f912f629fd6adf7e`) by
`scripts/cascade_gate.sh`:

| configuration | macro-F1 | accuracy | misclassified |
| --- | --- | --- | --- |
| rules only | 0.9791 | 0.9792 | 2 |
| full cascade, checkpoint `setfit_model_20260306_175404` | 0.9582 | 0.9583 | 4 |

Delta: **−0.0210 macro-F1**. The learned layers make it worse. Verdict recorded
in `backend/data/evaluation/baseline_cascade_v3.json` as
`comparison.verdict = behind_rules`, `promotable = false`.

Which layers answered, from the same run: `rules=58`, `setfit=20`,
`fallback=13`, `content_filter=5` — and `embeddings=0`, because the gate runs
against an empty embedding store on purpose (see "Why the store is empty"
below).

The delta is not diffuse. SetFit answered 20 of the 96 and the exchange is
one-for-three, recorded per example in `comparison.fixed_vs_reference` and
`comparison.broken_vs_reference`:

- **Fixed** — one the rules layer got wrong: *Follow-up after completing
  assessment*, `follow_up` misread as `assessment`.
- **Broken** — three the rules layer got right, all three answered by SetFit:
  *Submission confirmed for Product Analytics role* and *Receipt: application
  for Site Reliability Engineer*, both `applied` pulled to
  `pending_application`; and *Interview prep webinar this Thursday*, an `other`
  pulled to `interview`.
- **Shared** — *Thank you for interviewing with us*, `rejection` read as
  `other`, missed by both and answered by the fallback path.

So the learned layer is not uniformly worse; it is worse on the
`applied` / `pending_application` boundary and on promotional mail that reads
like an interview. That is a training-data shape, and it is where a retrain
would have to show improvement.

Two notes on that table, so neither reads as a correction later:

- The cascade number is reproducible from the checkpoint alone. Both checkpoints
  on this machine — `setfit_model_20260228_131948`, contemporary with Cycle H,
  and `setfit_model_20260306_175404` — produce the identical metrics and the
  identical four mismatches, differing only in how many examples SetFit chose to
  answer (22 vs 20).
- `docs/ML_EXECUTION_TRACKER.md` Cycle H records this configuration as
  `macro_f1=0.9583`. The measured value is 0.9581695…, which is 0.9582 at four
  decimals; 0.9583 is the accuracy. Cycle H is the historical record of what was
  run in March and is left exactly as it stands — `README.md` and
  `scripts/readme_facts.py` both pin it. From here the number to compare against
  is the one in `baseline_cascade_v3.json`, which was produced by a run whose
  artifacts are named in the file.

## The rule

A learned layer may serve real user mail only when **all** of these hold.

1. **It beats rules-only by a stated margin.** At least `PROMOTION_MARGIN`
   (0.005 macro-F1, defined in
   `backend/jobtracker/scripts/evaluate_classifier.py`) on the committed
   evaluation set, measured by `scripts/cascade_gate.sh` with the exact
   checkpoint that would be deployed. Not the newest checkpoint, not a
   re-training of it: that directory.
2. **The measurement shows the learned layers answering.** `layers.setfit > 0`
   or `layers.embeddings > 0` in the report. A cascade run that degraded to the
   rules layer scores 0.9791 and passes every other check, which is the exact
   failure this repository has shipped before; `_assert_layers_exercised`
   refuses it, and `--allow-degraded-layers` must not appear in a promotion run.
3. **Promotion is its own commit.** Retraining writes a checkpoint. It does not
   change what serves, and must not: the serving path is selected by
   `settings.lite_mode` and by the `deployment == "cloud"` rules-only
   short-circuit in `jobtracker/classifier/hybrid.py`. Changing either is a
   reviewed change that names the checkpoint, links the gate run, and quotes the
   delta. A retrain that flipped the serving path as a side effect would promote
   a model nobody measured.
4. **The baseline moves with it.** Re-record
   `backend/data/evaluation/baseline_cascade_v3.json` in the same change
   (`scripts/cascade_gate.sh --update-baseline`) and rebuild
   `benchmark_history.{md,jsonl}`. The recorded `artifacts` block — checkpoint
   directory, base model, `trained_at`, training-example count and source
   counts — is what makes the new number attributable.
5. **The sample size is stated, not implied.** 96 examples, 12 per label. A
   0.005 margin on 96 examples is roughly half of one example; a promotion note
   that does not say so is overselling the measurement. Prefer a margin the
   evaluation set can actually support, and grow the set before tightening it.
6. **Nothing is promoted on a set it was trained on.** The v3 corpus is an
   evaluation set. If a future retrain draws from it, the promotion measurement
   moves to a corpus that retrain did not see.

## What puts it back

Roll back to the rules-only serving path when any of these is observed:

- The cascade gate goes red against the committed baseline at `--tolerance
  0.001`, on overall metrics or on any per-label F1. Either the checkpoint
  drifted or the classifier around it changed; both mean the deployed
  configuration is no longer the measured one.
- Macro-F1 falls below the 0.95 floor `backend-ci.yml` enforces for the rules
  gate. That floor is the product's stated minimum and does not become optional
  because a model is in the path.
- A per-label collapse that the macro average hides — most plausibly
  `applied` / `pending_application`, which is where SetFit already loses
  examples, or the `assessment` / `follow_up` pair that
  `ml-monitoring-weekly.yml` watches.
- The weekly monitoring report raises a low-confidence-growth or
  distribution-drift alert that coincides with a promotion.
- User corrections rise after a promotion: corrections are the product's own
  signal that the classifier got worse, and they are already recorded per user
  in `training_data`.

Rolling back is reverting the promotion commit — the serving path returns to
rules-only, which is what production runs today anyway. The previous checkpoint
is still on disk (`MAX_SAVED_MODELS = 3`), so restoring a known-good model is
pointing at that directory, not a retrain. **Never** re-record the baseline to
make a red gate green; the baseline moves only when a better classifier is
deliberately promoted.

## Why the store is empty

`scripts/cascade_gate.sh` points the run at a scratch data directory holding
nothing but a link to the checkpoint, so the embedding store starts empty. That
is deliberate twice:

- The real store is built from *this user's* mail. A baseline recorded against
  it would be neither reproducible by anyone else nor publishable.
- With the store empty, the score is a function of the checkpoint alone, which
  is what makes "which artifact produced this verdict" answerable.

The consequence is stated rather than hidden: this gate does not measure what
the embedding layer contributes on a populated store. That is a genuine gap, and
closing it needs a shareable, non-personal example store — not a baseline
recorded against private data.

## Where this can run

| Where | What it measures |
| --- | --- |
| `backend-ci.yml`, every backend change | rules, and hybrid under `deterministic`. No learned layer, by design — a gate that consults a stochastic model goes red for reasons unrelated to the change under test |
| `learning-gate.yml`, `workflow_dispatch` | the full cascade. On a GitHub-hosted runner it **fails**, naming the directory it searched: no checkpoint ships in this repository |
| `scripts/cascade_gate.sh`, locally | the full cascade, where the checkpoint actually is |

That hosted-CI failure is the honest state of things, not an oversight. Making
it green means publishing a checkpoint the workflow can download — and that
decision has now been made, in the negative.

**Settled 2026-08-15: no checkpoint gets published.**

The consequence for this gate is that it stays red on hosted CI, permanently,
and that is now the intended state rather than a gap waiting to be closed. The
only thing that would change it is a checkpoint trained on synthetic data only
— `backend/tests/corpus/` is the intended source — which has not been run.

## Provenance of the withdrawn checkpoint

Written for a reader with no context and no reason to trust the author. Every
claim below is checkable from this repository or from the commit timeline.

**Which checkpoint.** `setfit_model_20260306_175404` — the directory name is
local time and `trained_at` is UTC (`2026-03-06T22:54:04`), which is the same
instant. This matters because a **sibling checkpoint from the same day**,
`setfit_model_20260306_153417`, records an identical `user_correction: 39` of
`total_examples: 192`, so the counts alone do not identify one. `_175404` is
the published one, confirmed twice: the timestamp, and the fact that it is the
copy `package_space.py` staged at
`ml/demo/space/appdata/models/setfit/setfit_model_20260306_175404`.

**What was trained.** A SetFit few-shot classifier, fine-tuned offline on
`sentence-transformers/paraphrase-MiniLM-L6-v2`. 192 examples: 39 user
corrections, 103 synthetic seeds (`mock_seed*`), 50 from an external dataset.

**Where the 39 came from — iCloud IMAP, not Gmail.** This is the fact most
likely to be assumed wrongly, so it is measured rather than inferred. The
desktop-era store still exists at
`~/Library/Application Support/JobTracker/jobtracker.db` and answers directly:

| Check | Result |
| --- | --- |
| `SELECT source_account, COUNT(*) FROM emails GROUP BY 1` | `ICLOUD` — 856 rows, and no other value has ever existed |
| `thread_id` populated (a Gmail-only column) | **0** of 856 |
| `sync_state` | exactly one row: `icloud`, `aesh_1055@icloud.com`, `gmail_history_id` NULL, `imap_last_uid` 11226 |
| `user_corrected` messages | 81, every one `ICLOUD` |
| `training_data` where `source='user_correction'` | 81 rows |

A Gmail client shipped in that build and the UI exposed it, but it was never
authenticated or run on that machine. **Google's Workspace API user-data policy
therefore never governed this corpus**, and any reasoning that starts from
"Applied reads Gmail under `gmail.readonly`" is reasoning about today's
architecture, not about the March tree that produced these weights.

**Whose mail it was.** The developer-owner's own, and no one else's:
`aesh_1055@icloud.com`, a single-user desktop application over local SQLite,
with no hosted deployment and no mechanism by which another person's mail could
reach the corpus. The project's first two authentication accounts were not
created until 2026-07-17 and 2026-07-19, four months later.

**The rows are recoverable.** An earlier revision of this note claimed they were
not. That was wrong and never checked against the filesystem: the **81-row
superset is intact** in the store above. Against the checkpoint's own
`label_source_counts`, 15 of the 39 are exactly identifiable today and the other
24 were drawn from 66 surviving rows.

**So what was actually wrong.** Not a Gmail-policy violation — there was no
Google data involved. What was wrong was **publishing weights trained on a real
mailbox at all**, which is poor practice whoever the provider is and whoever
owns the mailbox, and which is why the artifact was withdrawn rather than
merely relabelled. The fitted head (`head.json`) and the embedding bank
(`examples.json`) went with the weights because both are derived from the same
fine-tuned encoder.

**The model card, and what was *not* published.** The checkpoint directory
contains an auto-generated `README.md` of **166,204 bytes, of which the
`### Model Labels` table is 157,256 — 94.6%** — verbatim training-example text,
including the owner's iCloud address, LinkedIn tracking URLs, unsubscribe links
and a quoted requisition number. **It was never published.** The Hugging Face
model repository has exactly two commits, both on 2026-07-17, and its
`README.md` is **723 bytes** — a short hand-written card — for the whole life of
the repository. What the 13 downloads could have obtained is the weights,
`model_head.pkl` and `training_metadata.json`; **not** message text. That local
card must never be uploaded.

**Where the artifacts are now.** Deleted from the tracked tree, blocked from
returning by `.gitignore`, and both Hugging Face surfaces set private. The
originals are retained offline by the owner at
`~/Documents/Projects/applied-ml-weights-archive/` with recorded SHA-256 sums;
nothing was destroyed. Two limits stay on the record: the blobs remain reachable
through this repository's git history, and the model repository had been
downloaded 13 times before it was closed. Those copies cannot be recalled, which
is precisely why this note exists.

**What runs in production.** Deterministic regex rules, and nothing else. The
hosted classifier has no model installed, no retrain path, and no checkpoint to
load. A user correction is recorded against that user's own account and flags
the message `user_corrected`; it does not train anything.

**What training is permitted now.** Default-deny, enforced in code rather than
by convention (`backend/jobtracker/classifier/setfit_model.py`). A retrain is
refused unless the corpus is **entirely synthetic** or the single user it
belongs to is on an **explicit owner allowlist**; a corpus spanning two users
raises instead of training, and an empty corpus is refused as well.

## Provenance a verdict needs

Recorded today in every report and baseline:

- the checkpoint directory name, its base model, `trained_at`, its
  training-example count and per-source counts;
- the embedding model name, whether it loaded, and how many examples the store
  held;
- the layer tally — which layer answered each example;
- the dataset path and its SHA-256, so a re-labelled corpus cannot silently
  change the meaning of a number;
- the rules-only comparison, its delta and the promotion verdict.

Still missing, and worth adding before any retrain is automated:

- **The code revision.** A report does not record the git SHA of the classifier
  it measured, so a score cannot be attributed to a rules change versus a model
  change.
- **A content hash of the checkpoint weights.** The directory name is a
  timestamp, and timestamps can collide across machines or be restored from a
  copy; a hash would identify the artifact itself.
- **Which training rows produced the checkpoint.** `training_metadata.json`
  records counts by source, not row identities, so a bad retrain cannot be
  traced to the examples that caused it. Row identities are user mail; whatever
  is recorded has to be an identifier, not the text.
