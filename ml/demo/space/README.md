---
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
committed eval set — that figure is the **rules** stage, not the full
cascade). Paste any job-pipeline email — synthetic examples provided;
no inbox is read, ever.

> **Not deployed, and it has no weights.** The trained checkpoint was
> withdrawn on 2026-08-15: it was fitted partly on mail read under
> Gmail's restricted `gmail.readonly` scope, which may not be
> redistributed. `package_space.py` still assembles this bundle from a
> local checkpoint; nothing here is published.
