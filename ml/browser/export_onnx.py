"""Export the fine-tuned SetFit pipeline for in-browser inference.

Produces ml/browser/artifacts/:
  model_quantized.onnx   — fine-tuned e5-small body, dynamic-int8
  tokenizer files        — for transformers.js
  head.json              — LogisticRegression coef/intercept + labels
  examples.json          — per-class embedding bank for the similarity layer

    backend/.venv311/bin/python ml/browser/export_onnx.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
MODEL = next((REPO / "ml/demo/space/appdata/models/setfit").iterdir())
OUT = REPO / "ml" / "browser" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    import joblib
    import numpy as np
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoTokenizer

    # 1. Body -> ONNX (fp32), then dynamic int8.
    print("exporting fine-tuned body to ONNX…", flush=True)
    ort = ORTModelForFeatureExtraction.from_pretrained(str(MODEL), export=True)
    ort.save_pretrained(str(OUT))
    tok = AutoTokenizer.from_pretrained(str(MODEL))
    tok.save_pretrained(str(OUT))
    fp32 = OUT / "model.onnx"
    q8 = OUT / "model_quantized.onnx"
    quantize_dynamic(str(fp32), str(q8), weight_type=QuantType.QInt8)
    print(f"quantized: {q8.stat().st_size/1e6:.1f} MB (fp32 {fp32.stat().st_size/1e6:.1f} MB)")

    # 2. Head -> JSON.
    head = joblib.load(MODEL / "model_head.pkl")
    labels_txt = (MODEL / "label_mapping.txt").read_text().strip().splitlines()
    mapping = {}
    for line in labels_txt:
        if ":" in line:
            k, v = line.split(":", 1)
            mapping[int(k.strip())] = v.strip()
    (OUT / "head.json").write_text(
        json.dumps(
            {
                "coef": np.asarray(head.coef_).round(6).tolist(),
                "intercept": np.asarray(head.intercept_).round(6).tolist(),
                "classes": [mapping.get(int(c), str(c)) for c in head.classes_],
            }
        )
    )
    print("head.json written; classes:", [mapping.get(int(c)) for c in head.classes_])

    # 3. Example bank for the embeddings-similarity layer (synthetic only).
    from sentence_transformers import SentenceTransformer

    bank = {
        "interview": ["We'd like to schedule a technical interview next week", "Interview availability for the SWE role", "Your onsite loop is confirmed for Thursday"],
        "applied": ["Thank you for applying, we received your application", "Your application has been submitted", "Application received for Backend Engineer"],
        "rejection": ["We decided to move forward with other candidates", "Unfortunately we will not be proceeding", "After careful consideration we won't move ahead"],
        "offer": ["We are thrilled to extend an offer", "Your offer letter and compensation details", "Congratulations, we'd like to make you an offer"],
        "assessment": ["Please complete the coding assessment within 5 days", "Your online assessment link", "Next step: a 90-minute technical assessment"],
        "follow_up": ["Following up on our conversation last week", "Just checking in about your application", "Circling back on next steps"],
        "pending_application": ["Your application is under review", "We are still reviewing applications", "Your candidacy is progressing through review"],
        "other": ["Your weekly job digest", "New jobs recommended for you", "Manage your notification preferences"],
    }
    st = SentenceTransformer(str(MODEL))
    out = []
    for label, texts in bank.items():
        vecs = st.encode([f"query: {t}" for t in texts], normalize_embeddings=True)
        for t, v in zip(texts, vecs):
            out.append({"label": label, "text": t, "vec": [round(float(x), 5) for x in v]})
    (OUT / "examples.json").write_text(json.dumps(out))
    print(f"examples.json: {len(out)} vectors")
    print("EXPORT_COMPLETE")


if __name__ == "__main__":
    main()
