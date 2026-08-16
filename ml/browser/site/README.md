---
title: Applied classifier — in your browser
emoji: 📬
colorFrom: gray
colorTo: gray
sdk: static
pinned: false
license: mit
---

The 3-layer email classifier behind Applied (rules → fine-tuned
embeddings → SetFit head), ported to quantized ONNX and running entirely
in the browser. No server; nothing pasted leaves the page. Verified
output-identical to the Python pipeline.

> **The model weights were withdrawn on 2026-08-15 and this Space is
> private.** The checkpoint was fitted partly on mail read under Gmail's
> restricted `gmail.readonly` scope; Google's Workspace API user-data
> policy forbids training on that data and reaches derived data too, so
> the artifact may not be redistributed. What remains here is the loader,
> the 201 rules and the tokenizer — no weights. Re-export a model locally
> with `ml/browser/export_onnx.py` to run it again. Restoring this as a
> public demo needs a checkpoint trained on synthetic data only.

On the 96-email v3 held-out set the full cascade scores **0.958** macro-F1
and the rules stage alone scores **0.979** — which is why the hosted app
classifies with the rules, and why all three layers run here instead. CI
gates the number at 0.95.
