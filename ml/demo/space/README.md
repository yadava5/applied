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
committed eval set). Paste any job-pipeline email — synthetic examples
provided; no inbox is read, ever.
