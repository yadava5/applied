"""Tests for SetFit training metadata artifact generation."""

import json
from pathlib import Path

from jobtracker.classifier.setfit_model import SetFitClassifier


def test_write_training_metadata_creates_expected_file(tmp_path: Path) -> None:
    classifier = SetFitClassifier()
    classifier._category_to_label = {"applied": 0, "rejection": 1}
    classifier._label_to_category = {0: "applied", 1: "rejection"}

    dataset = {
        "train": [1, 2, 3, 4],
        "test": [5],
    }
    labels = ["applied", "applied", "rejection"]

    classifier._write_training_metadata(tmp_path, labels, dataset)

    metadata_path = tmp_path / "training_metadata.json"
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["total_examples"] == 3
    assert payload["label_counts"] == {"applied": 2, "rejection": 1}
    assert payload["train_split_size"] == 4
    assert payload["eval_split_size"] == 1
    assert payload["base_model"] == "sentence-transformers/paraphrase-MiniLM-L6-v2"
