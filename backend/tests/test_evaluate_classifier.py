"""Tests for classifier evaluation harness utilities."""

from pathlib import Path

from jobtracker.classifier.embeddings import EmbeddingsClassifier
from jobtracker.scripts.evaluate_classifier import (
    PROMOTION_MARGIN,
    _configure_hybrid_profile,
    build_comparison,
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


def test_compute_report_records_which_layer_answered_each_mismatch() -> None:
    """A wrong answer is only actionable once you know which layer produced it."""
    dataset = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "classifier_eval_v1.jsonl"
    examples = load_dataset(dataset)[:3]
    expected = ["applied", "applied", "other"]
    predicted = ["applied", "other", "other"]

    report = compute_report(
        expected,
        predicted,
        examples,
        dataset_path=Path("dummy.jsonl"),
        mode="hybrid",
        methods=["rules", "setfit", "content_filter"],
    )

    assert [item["method"] for item in report["mismatches"]] == ["setfit"]


def test_compute_report_omits_the_layer_when_it_was_not_recorded() -> None:
    dataset = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "classifier_eval_v1.jsonl"
    examples = load_dataset(dataset)[:2]

    report = compute_report(
        ["applied", "other"],
        ["other", "other"],
        examples,
        dataset_path=Path("dummy.jsonl"),
        mode="rules",
    )

    assert "method" not in report["mismatches"][0]


def _overall(macro_f1: float, misclassified: int) -> dict:
    return {
        "accuracy": macro_f1,
        "macro_f1": macro_f1,
        "weighted_f1": macro_f1,
        "misclassified": misclassified,
    }


def test_build_comparison_measures_the_gap_to_rules() -> None:
    """
    The committed shape: the cascade loses to the rules layer on v3, and the
    report has to say so in a field rather than in a paragraph somewhere else.
    """
    cascade = {
        "meta": {"mode": "hybrid", "hybrid_profile": "full"},
        "overall": _overall(0.9582, 4),
        "mismatches": [
            {"subject": "Receipt: application", "expected": "applied", "predicted": "pending_application", "method": "setfit"},
            {"subject": "Thank you for interviewing", "expected": "rejection", "predicted": "other", "method": "fallback"},
        ],
    }
    rules = {
        "meta": {"mode": "rules"},
        "overall": _overall(0.9791, 2),
        "mismatches": [
            {"subject": "Follow-up after assessment", "expected": "follow_up", "predicted": "assessment", "method": "rules"},
            {"subject": "Thank you for interviewing", "expected": "rejection", "predicted": "other", "method": "rules"},
        ],
    }

    comparison = build_comparison(cascade, rules, promotion_margin=PROMOTION_MARGIN)

    assert comparison["verdict"] == "behind_rules"
    assert comparison["promotable"] is False
    assert comparison["delta"]["macro_f1"] < 0
    assert comparison["delta"]["misclassified"] == 2
    # Which examples changed hands, not just how many.
    assert [item["subject"] for item in comparison["fixed_vs_reference"]] == [
        "Follow-up after assessment"
    ]
    assert [item["subject"] for item in comparison["broken_vs_reference"]] == [
        "Receipt: application"
    ]
    assert comparison["broken_vs_reference"][0]["method"] == "setfit"


def test_build_comparison_requires_the_margin_not_merely_a_win() -> None:
    rules = {"meta": {"mode": "rules"}, "overall": _overall(0.9791, 2), "mismatches": []}

    narrow = build_comparison(
        {"meta": {"mode": "hybrid"}, "overall": _overall(0.9821, 2), "mismatches": []},
        rules,
        promotion_margin=0.005,
    )
    clear = build_comparison(
        {"meta": {"mode": "hybrid"}, "overall": _overall(0.9851, 1), "mismatches": []},
        rules,
        promotion_margin=0.005,
    )

    assert narrow["verdict"] == "ahead_of_rules"
    assert narrow["promotable"] is False, "ahead by less than the margin is not promotable"
    assert clear["promotable"] is True


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


class _FakeHybridClassifier:
    """Stands in for ``HybridClassifier``, but holds a REAL layer-2 instance.

    The embeddings half used to be a hand-written double carrying just
    ``_known_embeddings`` / ``_loaded``. That let the double drift away from
    the class it imitated: when layer 2 gained an owner-keyed load cache, a
    hand-written double would have kept this test green while the
    ``deterministic`` profile silently started re-reading the database.
    """

    def __init__(self) -> None:
        self._embeddings = EmbeddingsClassifier()
        self._embeddings._known_embeddings = [("x", "y")]
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
