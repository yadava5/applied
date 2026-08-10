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
output-identical to the Python pipeline; 0.979 macro-F1, CI-gated at 0.95.
