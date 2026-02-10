"""
Classifier Module
=================

3-layer hybrid email classifier for job application emails.

Layers:
-------
1. Rules (rules.py): Regex patterns for common ATS phrases
2. Embeddings (embeddings.py): Sentence similarity using e5-small-v2
3. SetFit (setfit_model.py): Few-shot ML trained on user corrections

The hybrid classifier (hybrid.py) combines all layers:
- High-confidence rule matches are accepted immediately
- Embedding similarity catches variations of labeled examples
- SetFit provides ML-based classification for complex cases

Categories:
-----------
- applied: Application confirmation
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
"""

from .embeddings import EmbeddingsClassifier, get_embeddings_classifier
from .hybrid import (
    ClassificationResult,
    HybridClassifier,
    get_hybrid_classifier,
)
from .rules import RulesClassifier, get_rules_classifier
from .setfit_model import SetFitClassifier, get_setfit_classifier

# Convenience alias
get_classifier = get_hybrid_classifier

__all__ = [
    # Main classifier
    "HybridClassifier",
    "ClassificationResult",
    "get_hybrid_classifier",
    "get_classifier",
    # Layer 1: Rules
    "RulesClassifier",
    "get_rules_classifier",
    # Layer 2: Embeddings
    "EmbeddingsClassifier",
    "get_embeddings_classifier",
    # Layer 3: SetFit
    "SetFitClassifier",
    "get_setfit_classifier",
]
