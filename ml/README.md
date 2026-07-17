# ml/ — the classifier as a hosted inference service

Phase-1 deliverables that turn the 3-layer hybrid email classifier
(rules → e5-small-v2 → SetFit; 182 tests; CI-gated at macro-F1 ≥ 0.95,
0.98 measured on the v3 eval set) into a standalone, deployable service
with an MLOps trail.

| File | What it is |
|---|---|
| `service.py` | Standalone sync facade — `classify(subject, body) → {category, confidence, method, layers_consulted, latency_ms}`. No Gmail/IMAP/macOS coupling. |
| `track_run.py` | Runs the CI-identical eval, logs params/metrics/report to **MLflow** (`ml/mlruns`), registers `jobtracker-hybrid-classifier`, promotes to the `production` alias only past the 0.95 floor. Mirrors the run to **W&B** (offline until `wandb login`). |
| `demo/app.py` | **Gradio** demo (HF-Spaces-ready): paste an email → stage + confidence + 3-layer decision trace. Synthetic examples only. |
| `bento_service.py` | **BentoML** REST service: `POST /classify`. |

Run everything with the backend venv (`backend/.venv311`), env
`JOBTRACKER_ENVIRONMENT=test`.

## Pending owner logins (everything else is done)

1. `wandb login` → rerun `track_run.py` (or `wandb sync ml/wandb/…`) → public W&B project link.
2. Hugging Face token → create the Space, push `demo/` + the SetFit model dir (`~/Library/Application Support/JobTracker/models/setfit/…`), set `JOBTRACKER_DATABASE_DIR` to the bundled path.
