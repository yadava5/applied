"""Contract checks for classifier_eval_v3 dataset coverage."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    return data


def test_eval_v3_dataset_matches_spec_contract() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    dataset_path = backend_dir / "data" / "evaluation" / "classifier_eval_v3.jsonl"
    spec_path = backend_dir / "data" / "evaluation" / "classifier_eval_v3_spec.json"

    spec = _load_json(spec_path)
    contract = spec["coverage_contract"]
    label_set = set(spec["schema"]["label_set"])

    rows: list[dict] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            assert isinstance(payload, dict)
            rows.append(payload)

    assert len(rows) == contract["total_examples"]

    label_counts = Counter(item["label"] for item in rows)
    assert set(label_counts) == label_set
    for label in label_set:
        assert label_counts[label] == contract["per_label_target"]

    confusion_counts = Counter(item.get("confusion_pair", "") for item in rows)
    for pair in contract["required_confusion_pairs"]:
        assert confusion_counts[pair] > 0


def test_eval_v3_dataset_contains_historical_miss_subjects() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    dataset_path = backend_dir / "data" / "evaluation" / "classifier_eval_v3.jsonl"
    spec_path = backend_dir / "data" / "evaluation" / "classifier_eval_v3_spec.json"

    spec = _load_json(spec_path)
    expected_subjects = set(spec["coverage_contract"]["historical_miss_subjects"])

    subjects: set[str] = set()
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            subjects.add(str(payload.get("subject", "")))

    assert expected_subjects.issubset(subjects)
