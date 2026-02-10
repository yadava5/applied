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
    from jobtracker.classifier import HybridClassifier

    classifier = HybridClassifier()
    label, confidence, method = await classifier.classify(email_text)
"""

# Imports will be added as modules are implemented
__all__: list[str] = []
