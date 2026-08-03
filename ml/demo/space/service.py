"""Standalone classifier service — the 3-layer hybrid, no app coupling.

Wraps ``jobtracker.classifier`` (rules -> e5 embeddings -> SetFit) behind
one synchronous call that returns a JSON-safe dict with the decision and
its layer attribution. No Gmail, no IMAP, no macOS paths: the only state
it touches is the model directory under ``JOBTRACKER_DATABASE_DIR``.

Usage:
    from ml.service import EmailClassifierService
    svc = EmailClassifierService()
    out = svc.classify("Interview availability", "We'd love to schedule...")
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Make the backend package importable when running from the repo root.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

LAYERS = ("rules", "embeddings", "setfit")


class EmailClassifierService:
    """Synchronous facade over the async 3-layer hybrid classifier."""

    def __init__(self) -> None:
        from jobtracker.classifier.hybrid import get_hybrid_classifier

        self._clf = get_hybrid_classifier()

    def classify(
        self,
        subject: str,
        body: str,
        sender_email: Optional[str] = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        result = asyncio.run(self._clf.classify(subject, body, sender_email))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        method = str(result.method)
        # Layer attribution: every layer up to and including the one that
        # answered was consulted; later layers never ran.
        consulted = []
        for layer in LAYERS:
            consulted.append(layer)
            if layer == method:
                break
        if method not in LAYERS:  # "fallback" and guards
            consulted = list(LAYERS)

        return {
            "category": result.category.value,
            "confidence": round(float(result.confidence), 4),
            "method": method,
            "needs_review": bool(result.needs_review),
            "layers_consulted": consulted,
            "details": result.details or {},
            "latency_ms": round(elapsed_ms, 1),
        }


_service: Optional[EmailClassifierService] = None


def get_service() -> EmailClassifierService:
    global _service
    if _service is None:
        _service = EmailClassifierService()
    return _service
