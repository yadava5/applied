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
> private.** The checkpoint was fitted partly on a real mailbox — iCloud
> IMAP, not Gmail — and published weights trained on anyone's real mail
> should not be redistributed. What remains here is the loader,
> the 220 rules and the tokenizer — no weights. To run it again:
> `ml/browser/export_onnx.py` writes to `ml/browser/artifacts/`, so copy
> `head.json` and `examples.json` into this directory and
> `model_quantized.onnx` to `model/onnx/model.onnx`. Restoring this as a
> *public* demo needs a checkpoint trained on synthetic data only.

On the 96-email v3 held-out set the full cascade scores **0.958** macro-F1
and the rules stage alone scores **0.979** — which is why the hosted app
classifies with the rules, and why all three layers run here instead. Those
two are one measurement from 2026-08-11 and are quoted as a pair for that
reason; the rules layer alone was re-recorded on 2026-09-07 at **0.9896**
(#446), and the cascade arm has not been re-run, so the gap is at least as
wide as it looks. CI gates the rules figure at 0.95.
