"""BentoML service exposing the hybrid classifier as a REST endpoint.

    cd <repo root>
    backend/.venv311/bin/bentoml serve ml.bento_service:JobTrackerClassifier

POST /classify  {"subject": "...", "body": "...", "sender_email": null}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bentoml
from pydantic import BaseModel

from ml.service import get_service


class ClassifyRequest(BaseModel):
    subject: str = ""
    body: str = ""
    sender_email: str | None = None


@bentoml.service(name="jobtracker_classifier", resources={"cpu": "1"})
class JobTrackerClassifier:
    def __init__(self) -> None:
        self.svc = get_service()

    @bentoml.api
    def classify(self, request: ClassifyRequest) -> dict:
        return self.svc.classify(request.subject, request.body, request.sender_email)
