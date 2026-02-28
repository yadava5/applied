"""Tests for SetFit training metadata artifact generation."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from jobtracker.classifier.setfit_model import (
    TRAINING_METADATA_SCHEMA_VERSION,
    SetFitClassifier,
    validate_training_metadata_contract,
)


def _valid_training_metadata_payload() -> dict:
    return {
        "schema_version": TRAINING_METADATA_SCHEMA_VERSION,
        "trained_at": "2026-02-28T10:30:00",
        "base_model": "sentence-transformers/paraphrase-MiniLM-L6-v2",
        "total_examples": 3,
        "label_counts": {"applied": 2, "rejection": 1},
        "source_counts": {"user_correction": 2, "external_dataset": 1},
        "label_source_counts": {
            "applied": {"user_correction": 2},
            "rejection": {"external_dataset": 1},
        },
        "label_to_id": {"applied": 0, "rejection": 1},
        "id_to_label": {"0": "applied", "1": "rejection"},
        "train_split_size": 2,
        "eval_split_size": 1,
        "max_saved_models": 3,
    }


def test_write_training_metadata_creates_expected_file(tmp_path: Path) -> None:
    classifier = SetFitClassifier()
    classifier._category_to_label = {"applied": 0, "rejection": 1}
    classifier._label_to_category = {0: "applied", 1: "rejection"}
    classifier._last_training_source_counts = {"external_dataset": 1, "user_correction": 2}
    classifier._last_training_label_source_counts = {
        "applied": {"user_correction": 2},
        "rejection": {"external_dataset": 1},
    }

    dataset = {
        "train": [1, 2],
        "test": [3],
    }
    labels = ["applied", "applied", "rejection"]

    classifier._write_training_metadata(tmp_path, labels, dataset)

    metadata_path = tmp_path / "training_metadata.json"
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    validate_training_metadata_contract(payload)

    assert payload["schema_version"] == TRAINING_METADATA_SCHEMA_VERSION
    assert payload["total_examples"] == 3
    assert payload["label_counts"] == {"applied": 2, "rejection": 1}
    assert payload["source_counts"] == {"external_dataset": 1, "user_correction": 2}
    assert payload["label_source_counts"] == {
        "applied": {"user_correction": 2},
        "rejection": {"external_dataset": 1},
    }
    assert payload["train_split_size"] == 2
    assert payload["eval_split_size"] == 1
    assert payload["base_model"] == "sentence-transformers/paraphrase-MiniLM-L6-v2"


def test_validate_training_metadata_contract_requires_schema_version() -> None:
    payload = _valid_training_metadata_payload()
    payload.pop("schema_version")

    with pytest.raises(ValueError, match="schema_version is required"):
        validate_training_metadata_contract(payload)


def test_validate_training_metadata_contract_allows_legacy_without_schema_version() -> None:
    payload = _valid_training_metadata_payload()
    payload.pop("schema_version")

    validate_training_metadata_contract(
        payload,
        allow_legacy_without_schema_version=True,
    )


def test_validate_training_metadata_contract_rejects_unsupported_schema_version() -> None:
    payload = _valid_training_metadata_payload()
    payload["schema_version"] = TRAINING_METADATA_SCHEMA_VERSION + 999

    with pytest.raises(ValueError, match="unsupported schema_version"):
        validate_training_metadata_contract(payload)


def test_validate_training_metadata_contract_rejects_mismatched_source_rollup() -> None:
    payload = deepcopy(_valid_training_metadata_payload())
    payload["source_counts"] = {"external_dataset": 0, "user_correction": 3}

    with pytest.raises(
        ValueError,
        match="source_counts must equal the sum of label_source_counts",
    ):
        validate_training_metadata_contract(payload)
