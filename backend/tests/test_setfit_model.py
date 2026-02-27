"""Unit tests for SetFit output parsing compatibility."""

import numpy as np
import pytest

from jobtracker.classifier.setfit_model import SetFitClassifier
from jobtracker.database.models import EmailCategory


class _FakeSetFitModel:
    def __init__(self, prediction):
        self._prediction = prediction

    def predict(self, _texts):
        return [self._prediction]

    def predict_proba(self, _texts):
        return np.array([[0.1, 0.9]], dtype=float)


def test_classify_supports_integer_label_predictions(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = SetFitClassifier()
    classifier._model = _FakeSetFitModel(1)
    classifier._label_to_category = {1: "rejection"}

    monkeypatch.setattr(classifier, "is_available", lambda: True)

    result = classifier.classify("subject", "body")

    assert result is not None
    category, confidence = result
    assert category == EmailCategory.REJECTION
    assert confidence == pytest.approx(0.9, abs=1e-6)


def test_classify_supports_string_label_predictions(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = SetFitClassifier()
    classifier._model = _FakeSetFitModel("follow_up")
    classifier._category_to_label = {"follow_up": 0}

    monkeypatch.setattr(classifier, "is_available", lambda: True)

    result = classifier.classify("subject", "body")

    assert result is not None
    category, _confidence = result
    assert category == EmailCategory.FOLLOW_UP


def test_classify_supports_numeric_string_predictions(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = SetFitClassifier()
    classifier._model = _FakeSetFitModel("2")
    classifier._label_to_category = {2: "offer"}

    monkeypatch.setattr(classifier, "is_available", lambda: True)

    result = classifier.classify("subject", "body")

    assert result is not None
    category, _confidence = result
    assert category == EmailCategory.OFFER
