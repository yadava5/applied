"""Assemble a self-contained Hugging Face Space at ml/demo/space/.

Bundles: the Gradio app, the backend `jobtracker` package (2.2MB source,
classifier + config only at import time), and the trained SetFit model.
Nothing else — no data, no credentials, no inbox code paths executed.

    backend/.venv311/bin/python ml/demo/package_space.py
    # then, once a HF token exists:
    #   huggingface-cli login  (or HF_TOKEN env)
    #   huggingface-cli upload-large-folder <user>/jobtracker-classifier \
    #       --repo-type=space ml/demo/space
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO / "backend"
SPACE = REPO / "ml" / "demo" / "space"

sys.path.insert(0, str(BACKEND))


def main() -> None:
    import os

    os.environ.setdefault("JOBTRACKER_ENVIRONMENT", "test")
    from jobtracker.classifier.setfit_model import get_latest_model_path

    model_src = get_latest_model_path()
    if model_src is None:
        raise SystemExit("no trained SetFit model found — aborting")

    if SPACE.exists():
        shutil.rmtree(SPACE)
    SPACE.mkdir(parents=True)

    # 1. Backend package (source only; caches excluded).
    shutil.copytree(
        BACKEND / "jobtracker",
        SPACE / "jobtracker",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # 2. The trained SetFit model, at the path get_latest_model_path()
    #    resolves when JOBTRACKER_DATABASE_DIR points at ./appdata.
    model_dst = SPACE / "appdata" / "models" / "setfit" / model_src.name
    shutil.copytree(model_src, model_dst)

    # 3. The Gradio app, adapted for the flat Space layout.
    app_src = (REPO / "ml" / "demo" / "app.py").read_text()
    app_src = app_src.replace(
        'sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))',
        'sys.path.insert(0, str(Path(__file__).resolve().parent))\n'
        'os.environ.setdefault("JOBTRACKER_ENVIRONMENT", "test")\n'
        'os.environ.setdefault("JOBTRACKER_DATABASE_DIR", str(Path(__file__).resolve().parent / "appdata"))',
    )
    app_src = app_src.replace("import sys\n", "import os\nimport sys\n", 1)
    app_src = app_src.replace("from ml.service import get_service", "from service import get_service")
    app_src = app_src.replace(
        'demo.launch(server_name="127.0.0.1", server_port=7861, show_error=True)',
        "demo.launch()",
    )
    (SPACE / "app.py").write_text(app_src)

    svc_src = (REPO / "ml" / "service.py").read_text()
    svc_src = svc_src.replace(
        'BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"',
        'BACKEND_DIR = Path(__file__).resolve().parent',
    )
    (SPACE / "service.py").write_text(svc_src)

    # 4. Space metadata + requirements.
    (SPACE / "README.md").write_text(
        """---
title: Applied — 3-layer email classifier
emoji: 📬
colorFrom: gray
colorTo: gray
sdk: gradio
app_file: app.py
pinned: false
license: mit
---

Rules → e5-small-v2 embeddings → SetFit, the hybrid classifier behind
Applied, CI-gated at a 0.95 macro-F1 floor (0.979 measured on the
committed eval set). Paste any job-pipeline email — synthetic examples
provided; no inbox is read, ever.
"""
    )
    (SPACE / "requirements.txt").write_text(
        "\n".join(
            [
                "gradio>=5",
                "setfit>=1.1",
                "sentence-transformers>=3",
                "torch>=2.4",
                "pydantic>=2",
                "pydantic-settings>=2",
                "sqlalchemy>=2",
                "aiosqlite",
                "keyring",
                "httpx",
            ]
        )
        + "\n"
    )

    total = sum(f.stat().st_size for f in SPACE.rglob("*") if f.is_file())
    print(f"space assembled at {SPACE}  ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
