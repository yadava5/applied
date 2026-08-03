"""Track the classifier evaluation in MLflow (+ optional W&B) and gate
model registration on the 0.95 macro-F1 floor.

Runs the SAME evaluation CI runs (jobtracker.scripts.evaluate_classifier,
hybrid deterministic profile, v3 dataset), logs params/metrics/artifacts
to a local MLflow store (./ml/mlruns), and registers the model version in
the MLflow Model Registry. The version is promoted to the "production"
alias ONLY if macro-F1 clears the same floor the CI gate enforces.

W&B logging runs in offline mode by default (WANDB_MODE=offline) so no
account is required; `wandb sync` publishes it later.

    cd <repo root>
    backend/.venv311/bin/python -m ml.track_run
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
PYTHON = BACKEND / ".venv311" / "bin" / "python"
DATASET = "data/evaluation/classifier_eval_v3.jsonl"
MIN_MACRO_F1 = 0.95
MODEL_NAME = "jobtracker-hybrid-classifier"

sys.path.insert(0, str(BACKEND))


def run_eval(mode: str, profile: str | None, out_path: Path) -> dict:
    # Mirror the CI gate exactly: committed baseline + tolerance. Without
    # --baseline the script compares against a perfect-1.0 default and
    # flags every sub-1.0 class as a regression.
    cmd = [
        str(PYTHON),
        "-m",
        "jobtracker.scripts.evaluate_classifier",
        "--mode",
        mode,
        "--dataset",
        DATASET,
        "--baseline",
        "data/evaluation/baseline_hybrid_v3.json",
        "--tolerance",
        "0.001",
        "--min-macro-f1",
        str(MIN_MACRO_F1),
        "--output",
        str(out_path),
    ]
    if profile:
        cmd += ["--hybrid-profile", profile]
    env = os.environ | {
        "JOBTRACKER_ENVIRONMENT": "test",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    subprocess.run(cmd, cwd=BACKEND, env=env, check=True, capture_output=True)
    return json.loads(out_path.read_text())


def main() -> int:
    import mlflow

    # sqlite backend: the plain filesystem store is in maintenance mode in
    # current MLflow and raises unless explicitly re-enabled.
    mlflow.set_tracking_uri(f"sqlite:///{REPO / 'ml' / 'mlflow.db'}")
    mlflow.set_experiment("jobtracker-classifier")

    with tempfile.TemporaryDirectory() as td:
        report_path = Path(td) / "hybrid_eval.json"
        report = run_eval("hybrid", "deterministic", report_path)
        overall = report["overall"]

        with mlflow.start_run(run_name="hybrid-deterministic-v3") as run:
            mlflow.log_params(
                {
                    "mode": "hybrid",
                    "profile": "deterministic",
                    "dataset": DATASET,
                    "layers": "rules,e5-small-v2,setfit",
                    "min_macro_f1_floor": MIN_MACRO_F1,
                }
            )
            mlflow.log_metrics(
                {
                    "accuracy": overall["accuracy"],
                    "macro_f1": overall["macro_f1"],
                    "weighted_f1": overall["weighted_f1"],
                }
            )
            for row in report.get("per_class", []):
                label = row.get("label") or row.get("category")
                if label and "f1" in row:
                    mlflow.log_metric(f"f1_{label}", row["f1"])
            mlflow.log_artifact(str(report_path))

            passed = overall["macro_f1"] >= MIN_MACRO_F1
            mlflow.set_tag("gate_min_macro_f1", "pass" if passed else "fail")

            # Register the evaluated configuration as a model version.
            # The "model" is a config-defined pipeline (rules + e5 +
            # SetFit checkpoint), not a picklable object, so the version
            # points at the run's artifact directory (which holds the
            # full eval report). Promote only on a passing gate.
            client = mlflow.tracking.MlflowClient()
            try:
                client.create_registered_model(MODEL_NAME)
            except Exception:
                pass  # already exists
            version = client.create_model_version(
                MODEL_NAME, source=run.info.artifact_uri, run_id=run.info.run_id
            )
            if passed:
                client.set_registered_model_alias(MODEL_NAME, "production", version.version)

        # Optional W&B mirror (offline unless the owner has logged in).
        os.environ.setdefault("WANDB_MODE", "offline")
        try:
            import wandb

            wb = wandb.init(
                project="jobtracker-classifier",
                name="hybrid-deterministic-v3",
                dir=str(REPO / "ml"),
                config={"dataset": DATASET, "min_macro_f1": MIN_MACRO_F1},
            )
            wb.log(
                {
                    "accuracy": overall["accuracy"],
                    "macro_f1": overall["macro_f1"],
                    "weighted_f1": overall["weighted_f1"],
                }
            )
            wb.finish()
        except Exception as exc:  # W&B must never break the MLflow record
            print(f"wandb skipped: {exc}", file=sys.stderr)

    print(
        json.dumps(
            {
                "macro_f1": overall["macro_f1"],
                "accuracy": overall["accuracy"],
                "gate": "pass" if passed else "fail",
                "registered": MODEL_NAME,
                "alias": "production" if passed else None,
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
