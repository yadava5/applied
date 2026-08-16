"""Gradio demo: paste a job-related email, watch the 3-layer classifier
decide — stage, confidence, and which layer answered.

Synthetic examples only; nothing here reads an inbox. Built for Hugging
Face Spaces (CPU basic) and equally runnable locally:

    cd <repo root>
    JOBTRACKER_ENVIRONMENT=test backend/.venv311/bin/python ml/demo/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import gradio as gr

from ml.service import get_service

# Load rules + e5 + SetFit at boot, not on the first visitor's click:
# cold model load costs ~20s; a warmed service answers in milliseconds.
print("warming classifier…", flush=True)
get_service().classify("warmup", "warmup body")
print("classifier ready", flush=True)

LAYER_BLURB = {
    "rules": "Regex rules answered instantly — the pattern is unambiguous.",
    "embeddings": "e5-small-v2 similarity matched a labeled example.",
    # NOT "trained on corrections": the shipped checkpoint was fitted partly on
    # mail read under Gmail's restricted scope, was withdrawn on 2026-08-15, and
    # a public label advertising it as correction-trained is the claim a CASA
    # reviewer reads. It is a few-shot head; say that and nothing more.
    "setfit": "SetFit (few-shot ML head) decided.",
    "fallback": "No layer was confident — routed to human review.",
}

EXAMPLES = [
    [
        "Interview availability — Software Engineer, Platform",
        "Hi Ayush, thanks for applying. We'd like to schedule a 45-minute technical interview next week. Could you share your availability on Tuesday or Wednesday?",
    ],
    [
        "Your application was received",
        "Thank you for applying to the Backend Engineer role. Our team is reviewing applications and will reach out if there's a match.",
    ],
    [
        "Update on your application",
        "After careful consideration, we've decided to move forward with other candidates. We appreciate the time you invested and encourage you to apply again.",
    ],
    [
        "Congratulations — offer details inside",
        "We're thrilled to extend an offer for the Machine Learning Engineer position. Your start date, compensation, and benefits are outlined in the attached letter.",
    ],
    [
        "Next step: online assessment",
        "As the next step in the process, please complete the coding assessment linked below within 5 days. It should take about 90 minutes.",
    ],
]


def classify(subject: str, body: str):
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject and not body:
        return "—", "Paste an email (or load an example) to classify it.", ""

    out = get_service().classify(subject, body)
    stage = out["category"].replace("_", " ")
    confidence = f"{out['confidence'] * 100:.1f}%"

    trace_lines = []
    for layer in ("rules", "embeddings", "setfit"):
        if layer in out["layers_consulted"]:
            mark = "●" if layer == out["method"] else "○"
            note = LAYER_BLURB[layer] if layer == out["method"] else "consulted, not confident enough"
            trace_lines.append(f"{mark} {layer} — {note}")
        else:
            trace_lines.append(f"· {layer} — never ran (an earlier layer answered)")
    if out["method"] == "fallback":
        trace_lines.append(f"● fallback — {LAYER_BLURB['fallback']}")

    headline = f"## {stage}\n**{confidence}** confident · answered by **{out['method']}** · {out['latency_ms']}ms"
    review = "⚠ queued for human review" if out["needs_review"] else "auto-classified (≥0.85)"
    return headline, "\n".join(trace_lines), review


with gr.Blocks(title="JobTracker — 3-layer email classifier") as demo:
    gr.Markdown(
        "# JobTracker · hybrid email classifier\n"
        "Rules → e5 embeddings → SetFit, gated in CI at a 0.95 macro-F1 floor "
        "(0.98 measured). Paste any job-pipeline email; no inbox is read, ever."
    )
    with gr.Row():
        with gr.Column():
            subject = gr.Textbox(label="Subject", placeholder="Interview availability — SWE")
            body = gr.Textbox(label="Body", lines=8, placeholder="Paste the email body…")
            btn = gr.Button("Classify", variant="primary")
            gr.Examples(examples=EXAMPLES, inputs=[subject, body], label="Try a synthetic example")
        with gr.Column():
            verdict = gr.Markdown(label="Verdict")
            trace = gr.Textbox(label="3-layer decision trace", lines=5, interactive=False)
            review = gr.Textbox(label="Review policy", interactive=False)
    btn.click(classify, inputs=[subject, body], outputs=[verdict, trace, review])
    subject.submit(classify, inputs=[subject, body], outputs=[verdict, trace, review])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7861, show_error=True)
