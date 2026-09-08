# Benchmark History

Auto-generated from `baseline_*_v*.json` files.

`profile` is the hybrid evaluation profile the baseline was recorded under.
`deterministic` disables SetFit and blanks the embedding examples for
machine-stable CI gating, so a `deterministic` hybrid row measures the
deterministic path -- which is why it matches the `rules` row exactly.

A `cascade` row is the same classifier with the learned layers switched on
and a SetFit checkpoint loaded, recorded by `scripts/cascade_gate.sh`. Its
gap to the `rules` row of the same version is the only measurement of what
the learned layers are worth. It is not produced by CI: no checkpoint ships
in this repository, so a GitHub-hosted runner has nothing to load.

| mode | version | profile | dataset | accuracy | macro_f1 | weighted_f1 | misclassified |
|------|---------|---------|---------|----------|----------|-------------|---------------|
| cascade | v3 | full | `data/evaluation/classifier_eval_v3.jsonl` | 0.9688 | 0.9686 | 0.9686 | 3 |
| hybrid | v1 | n/a | `data/evaluation/classifier_eval_v1.jsonl` | 1.0000 | 1.0000 | 1.0000 | 0 |
| hybrid | v2 | n/a | `data/evaluation/classifier_eval_v2.jsonl` | 0.8438 | 0.8598 | 0.8598 | 10 |
| hybrid | v3 | deterministic | `data/evaluation/classifier_eval_v3.jsonl` | 0.9896 | 0.9896 | 0.9896 | 1 |
| rules | v1 | n/a | `data/evaluation/classifier_eval_v1.jsonl` | 1.0000 | 1.0000 | 1.0000 | 0 |
| rules | v2 | n/a | `data/evaluation/classifier_eval_v2.jsonl` | 0.8594 | 0.8738 | 0.8738 | 9 |
| rules | v3 | n/a | `data/evaluation/classifier_eval_v3.jsonl` | 0.9896 | 0.9896 | 0.9896 | 1 |
