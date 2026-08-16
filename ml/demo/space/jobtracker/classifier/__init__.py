"""
Classifier Module
=================

3-layer hybrid email classifier for job application emails.

Layers:
-------
1. Rules (rules.py): Regex patterns for common ATS phrases
2. Embeddings (embeddings.py): Sentence similarity using e5-small-v2
3. SetFit (setfit_model.py): Few-shot ML, fit offline on a labelled corpus
   (synthetic seeds and public-dataset rows). NOT trained on user
   corrections: nothing hosted retrains, and a training run refuses any
   user who is not on JOBTRACKER_TRAINING_ALLOWED_USER_IDS. See the
   module header in setfit_model.py for why that is a policy constraint.

The hybrid classifier (hybrid.py) combines all layers:
- High-confidence rule matches are accepted immediately
- Embedding similarity catches variations of labeled examples
- SetFit provides ML-based classification for complex cases

Categories:
-----------
- applied: Application confirmation
- pending_application: Started/not-yet-submitted application reminder
- interview: Interview invitation
- rejection: Rejection notice
- offer: Job offer
- assessment: Technical assessment request
- follow_up: Follow-up email
- other: Non-job-related

Usage:
------
    from jobtracker.classifier import get_classifier

    classifier = get_classifier()
    result = await classifier.classify(subject, body, sender_email)
    print(f"Category: {result.category.value}")
    print(f"Confidence: {result.confidence}")

Cloud import hygiene
--------------------
``embeddings`` and ``setfit_model`` are NOT imported at package load time.
They are exposed lazily via ``__getattr__`` so that
``from jobtracker.classifier import get_classifier`` on the Vercel cloud
deployment does not pull ``numpy``, ``sentence-transformers``, ``torch``,
or ``setfit`` into ``sys.modules``. Issue #17 (C6) enforces this via a
subprocess-isolated test in ``backend/tests/test_main_cloud.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .hybrid import (
    ClassificationResult,
    HybridClassifier,
    get_hybrid_classifier,
)
from .rules import RulesClassifier, get_rules_classifier

# Convenience alias — matches the previous public API.
get_classifier = get_hybrid_classifier

if TYPE_CHECKING:  # pragma: no cover - types only, never imported at runtime
    from .embeddings import EmbeddingsClassifier, get_embeddings_classifier
    from .setfit_model import SetFitClassifier, get_setfit_classifier


# Heavy submodule attributes are resolved on first attribute access so
# desktop callers keep their ergonomic ``from jobtracker.classifier import
# SetFitClassifier`` path while cloud callers (which never touch these
# names) pay zero import cost.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "EmbeddingsClassifier": ("jobtracker.classifier.embeddings", "EmbeddingsClassifier"),
    "get_embeddings_classifier": (
        "jobtracker.classifier.embeddings",
        "get_embeddings_classifier",
    ),
    "SetFitClassifier": ("jobtracker.classifier.setfit_model", "SetFitClassifier"),
    "get_setfit_classifier": (
        "jobtracker.classifier.setfit_model",
        "get_setfit_classifier",
    ),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy module attribute hook for heavy re-exports."""

    if name in _LAZY_EXPORTS:
        import importlib

        module_path, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_path)
        value = getattr(module, attr)
        globals()[name] = value  # cache for future access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Main classifier
    "HybridClassifier",
    "ClassificationResult",
    "get_hybrid_classifier",
    "get_classifier",
    # Layer 1: Rules
    "RulesClassifier",
    "get_rules_classifier",
    # Layer 2: Embeddings (lazy)
    "EmbeddingsClassifier",
    "get_embeddings_classifier",
    # Layer 3: SetFit (lazy)
    "SetFitClassifier",
    "get_setfit_classifier",
]
