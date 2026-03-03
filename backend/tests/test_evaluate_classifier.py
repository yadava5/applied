"""Tests for classifier evaluation harness utilities."""

from pathlib import Path

from jobtracker.scripts.evaluate_classifier import (
    _configure_hybrid_profile,
    compare_against_baseline,
    compute_report,
    load_dataset,
)


def test_load_dataset_supports_body_alias(tmp_path: Path) -> None:
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        "\n".join(
            [
                '{"subject":"A","body":"B","label":"applied"}',
                '{"subject":"C","body_text":"D","label":"other"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = load_dataset(dataset)

    assert len(rows) == 2
    assert rows[0].body_text == "B"
    assert rows[1].body_text == "D"


def test_compute_report_generates_expected_metrics() -> None:
    dataset = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "classifier_eval_v1.jsonl"
    examples = load_dataset(dataset)[:4]
    expected = ["applied", "applied", "other", "other"]
    predicted = ["applied", "other", "other", "other"]

    report = compute_report(
        expected,
        predicted,
        examples,
        dataset_path=Path("dummy.jsonl"),
        mode="rules",
    )

    assert report["overall"]["accuracy"] == 0.75
    assert report["per_label"]["applied"]["recall"] == 0.5
    assert report["per_label"]["other"]["precision"] == 2 / 3
    assert report["overall"]["misclassified"] == 1


def test_compare_against_baseline_flags_f1_regression() -> None:
    report = {
        "overall": {"accuracy": 0.90, "macro_f1": 0.89, "weighted_f1": 0.90},
        "per_label": {
            "applied": {"f1": 0.8, "support": 5},
            "other": {"f1": 0.95, "support": 5},
        },
    }
    baseline = {
        "overall": {"accuracy": 0.91, "macro_f1": 0.90, "weighted_f1": 0.91},
        "per_label": {
            "applied": {"f1": 0.85, "support": 5},
            "other": {"f1": 0.95, "support": 5},
        },
    }

    failures = compare_against_baseline(report, baseline, tolerance=0.0)

    assert any("overall.accuracy" in msg for msg in failures)
    assert any("overall.macro_f1" in msg for msg in failures)
    assert any("per_label.applied.f1" in msg for msg in failures)


class _FakeEmbeddings:
    def __init__(self) -> None:
        self._known_embeddings = [("x", "y")]
        self._loaded = False


class _FakeHybridClassifier:
    def __init__(self) -> None:
        self._embeddings = _FakeEmbeddings()
        self.lite_mode_enabled = False

    def set_lite_mode(self, enabled: bool) -> None:
        self.lite_mode_enabled = enabled


def test_configure_hybrid_profile_deterministic_disables_semantic_state() -> None:
    classifier = _FakeHybridClassifier()

    _configure_hybrid_profile(classifier, "deterministic")

    assert classifier.lite_mode_enabled is True
    assert classifier._embeddings._loaded is True
    assert classifier._embeddings._known_embeddings == []


def test_configure_hybrid_profile_rejects_unknown_profile() -> None:
    classifier = _FakeHybridClassifier()

    try:
        _configure_hybrid_profile(classifier, "unknown-profile")
    except ValueError as exc:
        assert "Unsupported hybrid profile" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported hybrid profile")
