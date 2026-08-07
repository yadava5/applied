# What these MLflow artifacts are, and what they do not show

Three tracked JSON files live here. They are evidence, not build inputs: nothing
in the app, in CI, or in the deployed function reads them. They are kept because
they are the recorded provenance of published numbers.

## `1/*/artifacts/hybrid_eval.json` — the 0.979 figure

Both runs report 96 samples, 94 correct: accuracy `0.97917`, macro-F1 `0.97913`.
That is the **0.979** quoted in the README, the résumé and the system card.

The file self-describes as `"mode": "hybrid"`. **Read that with the profile next
to it:** the same object records `"hybrid_profile": "deterministic"`, and
`ml/track_run.py:77` invokes `run_eval("hybrid", "deterministic")`.

The deterministic profile switches **both** semantic layers off. Verified by
execution, not by reading:

- `set_lite_mode(True)` makes `classifier/hybrid.py:372` short-circuit before
  `self._setfit` is ever read, so the SetFit module is never imported.
- The embedding store is emptied, so `classifier/embeddings.py:294` returns
  `None` from `classify()`.

The check that matters: on a machine where the e5 model **does** load,
`is_available()` returns `True` and `classify()` still returns `None`. The
profile does not merely depend on the model being absent.

So this artifact is a **rules-path measurement**. It is not a measurement of the
three-layer cascade. `backend/data/evaluation/baseline_rules_v3.json` carries
identical metrics and identical mismatches, and remains the canonical evidence
for the published figure.

## Why that is the right number to publish anyway

Production never runs the cascade. `vercel.json` sets
`JOBTRACKER_DEPLOYMENT=cloud`; with `env_prefix="JOBTRACKER_"`
(`backend/jobtracker/config.py:42`) that reaches `settings.deployment`, which
sets `_cloud_rules_only = True` (`classifier/hybrid.py:156`), which makes
`hybrid.py:275` return straight after the rules layer for every input. The
deployed classifier does not reach the embedding or SetFit branches at all.

## The one caveat — do not overstate the equivalence

"Deterministic hybrid equals rules" is **not** true in general, and
`backend/data/evaluation/benchmark_history.md` slightly overstates it.

A content-guard pre-veto at `hybrid.py:227-241` runs *before* the rules layer,
so on a guard hit the rules verdict is never consulted. A worked counterexample:

    subject "Complete your online assessment"
    body    "Please finish it. Unsubscribe | Manage preferences"
      rules  -> assessment  0.95
      hybrid -> other       0.96  (method=content_filter)

On this particular 96-sample set the two agree everywhere: 91 samples never
touch the guard, and the 5 that do are ones rules independently scored `other`.
That is a property of the dataset, not a guarantee from the code. The guard is
live in production too, so 0.979 does not describe the deployed decision
function on guard-hit mail.

## Known gaps

- The artifacts were generated 2026-07-17 (`973f99d`); the `layers` key and
  `_assert_layers_exercised` arrived 2026-08-02 (`8d040b8`). They predate the
  instrumentation and cannot certify what ran — which is why the reasoning above
  is by execution rather than by trusting the file.
- That guard still would not catch them: `evaluate_classifier.py:186` returns
  `[]` unless the profile is `full`, and **no automated path runs `full`** —
  `backend-ci.yml:95` and `scripts/ml_cycle.sh` all pass `deterministic`.
  **Nothing in this repo has ever benchmarked the actual cascade.**
- Run `6e4caa26...` has MLflow status `FAILED` yet a `gate_min_macro_f1=pass`
  tag. Only `41705c17...` backs the registered model version. Why the other run
  failed is not established.

## `2/*/artifacts/fidelity.json`

The synthetic-vs-real fidelity study (n=100000;
`surrogate_vs_real_auc_median_threshold` 0.9603, `published_real_holdout_auc`
0.8976). No duplicate exists anywhere in the repo — this is the only copy.
