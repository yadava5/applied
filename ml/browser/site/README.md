---
title: Applied classifier — in your browser
emoji: 📬
colorFrom: gray
colorTo: gray
sdk: static
pinned: false
license: mit
---

The 3-layer email classifier behind Applied (rules → fine-tuned e5
embeddings → SetFit head), ported to quantized ONNX and running entirely
in the browser. No server; nothing pasted leaves the page. Verified
output-identical to the Python pipeline.

On the 96-email v3 held-out set the full cascade scores **0.958** macro-F1
and the rules stage alone scores **0.979** — which is why the hosted app
classifies with the rules, and why all three layers run here instead. CI
gates the number at 0.95.
