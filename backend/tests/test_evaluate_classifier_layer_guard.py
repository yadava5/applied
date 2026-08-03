"""
Guards on the classifier benchmark's own honesty.

These do not test the classifier. They test the two ways its evaluation harness
could report a number that is true of a *different* classifier than the one named
on the command line -- both of which it did, before these existed.

The background, because it is the whole reason this file exists:

``HybridClassifier`` degrades on purpose. When setfit or sentence-transformers
will not import, it logs a warning and answers from the rules layer, because the
running API must keep classifying mail when the model is missing. That is correct
for the application and quietly fatal for the benchmark: on the committed v3 set
the rules layer and the hybrid cascade both score macro-F1 0.9791 -- see
``data/evaluation/benchmark_history.md``, and note that ``baseline_rules_v3.json``
and ``baseline_hybrid_v3.json`` agree to sixteen decimal places and were written
six seconds apart. So a hybrid run with every model dead produces 0.9791, matches
the committed baseline, prints PASS, and is indistinguishable from a healthy one.

Observed, not hypothesised. Under transformers 5.14.1, setfit 1.1.3 raises
``ImportError: cannot import name 'default_logdir' from
'transformers.training_args'``; the hybrid evaluation then scored 0.9791 and
passed, having loaded no model at all.
"""

from __future__ import annotations

from jobtracker.scripts.evaluate_classifier import (
    SEMANTIC_LAYERS,
    _assert_layers_exercised,
    compare_against_baseline,
)


def _report(layers: dict[str, int], *, profile: str = "full") -> dict:
    return {"meta": {"mode": "hybrid", "hybrid_profile": profile}, "layers": layers}


def test_hybrid_full_fails_when_only_deterministic_layers_answered() -> None:
    """The exact shape of a lite-mode run: no model loaded, still scores 0.9791."""
    failures = _assert_layers_exercised(
        _report({"content_filter": 5, "fallback": 33, "rules": 58}),
        mode="hybrid",
        hybrid_profile="full",
    )
    assert failures, "a hybrid/full run with no semantic layer must not be accepted"
    assert "embeddings/setfit" in failures[0]


def test_content_filter_alone_does_not_count_as_a_semantic_layer() -> None:
    """
    Regression test for a bug in the first version of this guard.

    That version asked for any layer that was not rules-or-fallback, which
    ``content_filter`` satisfies. But content_filter is a deterministic veto that
    fires ahead of the rules layer as well as inside the semantic branches
    (hybrid.py:238 vs :353/:398), so it appears in a run where nothing loaded --
    and the guard passed the very run it was written to catch. The check is an
    allowlist of the two layers that are actually models for exactly this reason.
    """
    assert "content_filter" not in SEMANTIC_LAYERS
    assert {"embeddings", "setfit"} == SEMANTIC_LAYERS

    failures = _assert_layers_exercised(
        _report({"content_filter": 40, "rules": 56}),
        mode="hybrid",
        hybrid_profile="full",
    )
    assert failures, "content_filter is not evidence that a model ran"


def test_hybrid_full_passes_when_a_model_answered() -> None:
    for layer in sorted(SEMANTIC_LAYERS):
        assert not _assert_layers_exercised(
            _report({"rules": 58, "fallback": 13, "content_filter": 5, layer: 20}),
            mode="hybrid",
            hybrid_profile="full",
        ), f"{layer} answering must be accepted"


def test_deterministic_profile_is_not_required_to_run_models() -> None:
    """
    The deterministic profile disables SetFit and blanks the embedding examples by
    design, for machine-stable CI gating. Demanding semantic layers there would be
    demanding the opposite of what the profile is for.
    """
    assert not _assert_layers_exercised(
        _report({"rules": 58, "fallback": 33, "content_filter": 5}, profile="deterministic"),
        mode="hybrid",
        hybrid_profile="deterministic",
    )


def test_rules_mode_is_not_subject_to_the_layer_check() -> None:
    assert not _assert_layers_exercised(
        {"meta": {"mode": "rules"}, "layers": {"rules": 96}},
        mode="rules",
        hybrid_profile="full",
    )


def test_full_run_is_not_compared_against_a_deterministic_baseline() -> None:
    """
    The committed hybrid baseline carries ``hybrid_profile: deterministic``, while
    ``--mode hybrid`` defaults to ``--hybrid-profile full``. Comparing them scores
    the cascade against the rules number, so every contribution the semantic layers
    make reads as a regression.
    """
    current = {
        "meta": {"mode": "hybrid", "hybrid_profile": "full"},
        "overall": {"accuracy": 0.9583, "macro_f1": 0.9582, "weighted_f1": 0.9582},
        "per_label": {},
    }
    baseline = {
        "meta": {"mode": "hybrid", "hybrid_profile": "deterministic"},
        "overall": {"accuracy": 0.9792, "macro_f1": 0.9791, "weighted_f1": 0.9791},
        "per_label": {},
    }

    failures = compare_against_baseline(current, baseline, tolerance=0.0)
    assert failures, "profiles differ; the comparison is not meaningful"
    assert "hybrid_profile mismatch" in failures[0]
    assert len(failures) == 1, "the mismatch must short-circuit, not add to metric noise"


def test_matching_profiles_still_compare_metrics() -> None:
    same = {"meta": {"mode": "hybrid", "hybrid_profile": "deterministic"}}
    current = {
        **same,
        "overall": {"accuracy": 0.90, "macro_f1": 0.89, "weighted_f1": 0.90},
        "per_label": {},
    }
    baseline = {
        **same,
        "overall": {"accuracy": 0.95, "macro_f1": 0.94, "weighted_f1": 0.95},
        "per_label": {},
    }

    failures = compare_against_baseline(current, baseline, tolerance=0.0)
    assert any("overall.macro_f1" in f for f in failures)
    assert not any("hybrid_profile mismatch" in f for f in failures)
