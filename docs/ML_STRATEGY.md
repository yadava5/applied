# ML Strategy: Email Classification

## Problem

Classify incoming emails into job application categories:

| Category | Example Email |
|----------|--------------|
| `applied` | "We received your application for Software Engineer" |
| `interview` | "We'd like to schedule an interview with you" |
| `rejection` | "We've decided to move forward with other candidates" |
| `offer` | "We're pleased to offer you the position of..." |
| `assessment` | "Please complete this take-home coding challenge" |
| `follow_up` | "Just checking in — any updates on my application?" |
| `other` | Not job-related or uncategorizable |

## Constraints

| Constraint | Detail |
|------------|--------|
| Budget | $0 — no paid APIs, no cloud compute |
| Hardware | Personal laptop, 8-16GB RAM, no GPU |
| Training data | None at start — no pre-existing labeled dataset |
| Privacy | All processing local — emails never leave the machine |
| Availability | Must work offline after initial model download |
| Day-1 usability | Must classify emails from the first run — no training period |

## Approach: 3-Layer Hybrid Classifier

```
Email arrives
     │
     ▼
┌──────────────────────┐
│  Layer 1: Rules      │  ← Instant, catches obvious patterns
│  (regex + keywords)  │    "regret to inform" → REJECTION (confidence: 0.95)
└────────┬─────────────┘
         │ Not confident enough?
         ▼
┌──────────────────────┐
│  Layer 2: Similarity │  ← Compares to emails you've labeled before
│  (MiniLM embeddings) │    "Similar to that Stripe rejection" (confidence: 0.88)
└────────┬─────────────┘
         │ Still not confident?
         ▼
┌──────────────────────┐
│  Layer 3: SetFit     │  ← ML model trained on YOUR corrections
│  (few-shot ML)       │    Trained on 40+ labeled examples
└────────┬─────────────┘
         │
    ┌────┴────┐
    ▼         ▼
 ≥ 0.7      < 0.7
 Auto-       Flag for
 classify    your review
```

---

## Layer 1: Rule-Based Classifier (Day 1 — no setup needed)

Pattern matching with weighted scoring. Job emails follow predictable templates from ATS systems (Greenhouse, Lever, Workday, etc.).

### How It Works

Each category has three pattern groups:
- **Strong patterns** (+3 score): highly specific phrases
- **Weak patterns** (+1 score): suggestive but ambiguous phrases
- **Negative patterns** (−5 score): phrases that contradict this category

Highest-scoring category wins. If the margin between top-2 scores is small, confidence is low.

### Pattern Examples

**Rejection:**
```
Strong:  "unfortunately", "decided not to proceed", "move forward with other candidates",
         "position has been filled", "not selected", "regret to inform"
Weak:    "thank you for your interest", "encourage you to apply", "future openings"
Negative: "interview", "excited to meet", "offer"
```

**Interview Request:**
```
Strong:  "schedule an interview", "interview invitation", "meet the team",
         "Calendly link", "Zoom meeting", "phone screen"
Weak:    "next steps", "your availability", "looking forward to speaking"
Negative: "unfortunately", "regret", "not moving forward"
```

**Job Offer:**
```
Strong:  "pleased to offer", "offer letter", "offer of employment",
         "compensation package", "start date", "annual salary"
Weak:    "benefits overview", "accept this offer", "we'd love to have you"
Negative: "unfortunately", "not at this time"
```

**Application Received:**
```
Strong:  "application received", "thank you for applying", "successfully submitted",
         "confirm receipt", "application for .* has been received"
Weak:    "review your application", "be in touch", "hearing from us soon"
Negative: "unfortunately", "offer", "interview"
```

### Additional Signal Sources

- **Sender domain rules**: `@greenhouse.io`, `@lever.co`, `@myworkday.com`, `@icims.com` → ATS system (likely job-related)
- **Subject line weighting**: Subject patterns weighted 2× vs body patterns (subjects are more predictable)
- **Header analysis**: `X-Mailer`, `List-Unsubscribe` headers can identify automated/ATS emails

### Performance

| Metric | Value |
|--------|-------|
| Memory | < 10MB |
| Speed | 1000+ emails/second |
| Setup time | 0 (built into the app) |
| Expected accuracy | 70–80% |

---

## Layer 2: Sentence Embeddings (Week 1 — after first user corrections)

Uses `all-MiniLM-L6-v2` to create vector representations of emails, then matches new emails against previously labeled ones using cosine similarity.

### How It Works

1. When the user corrects a misclassified email, compute its embedding (384-dimensional vector)
2. Store the embedding + correct label in the known examples store
3. For new emails: compute embedding → find most similar known example → use its label if similarity > 0.85

### Model Details

| Property | Value |
|----------|-------|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Size on disk | 80MB (downloaded once) |
| Embedding dimensions | 384 |
| Runtime RAM | ~200MB |
| Inference speed | ~50ms per email |
| Internet needed | Only once for download |

### When It Activates

This layer activates after the user has corrected at least 1 email. Each correction adds a new reference point. More corrections = better similarity matching.

### Why It Helps

Rule-based misses variations:
- Rule catches: *"We regret to inform you..."*
- Rule misses: *"After careful consideration, we've chosen to pursue candidates whose experience more closely aligns..."*
- Embedding catches it — it's semantically similar to other rejection emails already labeled.

---

## Layer 3: SetFit (Week 2-4 — after accumulating ~40 corrections)

SetFit (Sentence Transformer Fine-tuning) trains a classifier from as few as **5-10 examples per category** using contrastive learning on sentence embeddings.

### How It Works

1. Takes user-corrected examples from the `training_data` table
2. Creates contrastive pairs: (same-category emails = similar, different-category = dissimilar)
3. Fine-tunes the MiniLM embedding model on these pairs
4. Trains a logistic regression classifier on the tuned embeddings
5. Result: a fast, accurate classifier trained on YOUR specific emails

### Training Requirements

| Resource | Value |
|----------|-------|
| Minimum examples | 5-10 per category (40-70 total) |
| Training time | 2-5 minutes on CPU |
| Peak RAM during training | ~2GB |
| Model size after training | ~90MB |
| GPU required | No |

### When It Triggers

Auto-retrain when:
- At least 5 new corrections exist in *any* category since last training
- At least 3 categories have ≥ 5 examples
- User can also manually trigger via `POST /ml/retrain`

### Model Management

- Save trained models with timestamps: `setfit_model_20260209_103000/`
- Keep last 3 model versions (rollback capability)
- Load latest model on backend startup
- Retrain in background thread (non-blocking)

### Performance

| Examples | Expected Accuracy |
|----------|-------------------|
| 8 per class (40 total) | 75-85% |
| 20 per class (100 total) | 85-92% |
| 50+ per class (250+ total) | 90-95% |

---

## Hybrid Decision Logic

```python
def classify(email_text: str) -> tuple[str, float, str]:
    """Returns (label, confidence, method)"""

    # Layer 1: Rules
    rule_label, rule_confidence = rules_classify(email_text)
    if rule_confidence > 0.9:
        return rule_label, rule_confidence, "rules"

    # Layer 2: Embedding similarity
    if has_known_examples():
        embedding = embedder.encode(email_text)
        sim_label, sim_score = find_most_similar(embedding, known_examples)
        if sim_score > 0.85:
            return sim_label, sim_score, "similarity"

    # Layer 3: SetFit ML model
    if setfit_model is not None:
        ml_label = setfit_model.predict([email_text])[0]
        ml_confidence = setfit_model.predict_proba([email_text]).max()
        if ml_confidence > 0.7:
            return ml_label, ml_confidence, "setfit"

    # Fallback: return best available guess
    return rule_label or "other", max(rule_confidence, 0.5), "fallback"
```

## Confidence Thresholds

| Confidence | Action in App |
|------------|---------------|
| ≥ 0.85 | Auto-classify — no user review needed |
| 0.70 – 0.84 | Auto-classify — but show in "Review" queue with yellow badge |
| < 0.70 | Flag for manual review — show in review queue with red badge, don't auto-assign to application |

---

## User Correction Feedback Loop

This is how the app gets smarter over time, powered by YOUR fixes:

```
You see a misclassified email in the app
        │
        ▼
Click the category badge → pick correct category
        │
        ▼
App sends PUT /emails/{id}/classify { "classified_as": "interview" }
        │
        ├──► Correction saved to training_data table
        ├──► Email embedding stored in known_examples (Layer 2 improves immediately)
        └──► Check: enough new corrections to retrain?
                   │
                   ├── No → done (Layer 2 still improved)
                   └── Yes → retrain SetFit in background (2-5 min)
                              │
                              ▼
                         New model saved → loaded for future predictions
```

### What This Means In Practice

| Week | Your Effort | What Improves |
|------|-------------|----------------|
| Week 1 | Fix ~20 emails (2 min/day) | Layer 2 starts catching similar emails |
| Week 2 | Fix ~15 emails | SetFit trains for first time |
| Week 3 | Fix ~8 emails | SetFit retrains, getting better |
| Week 4+ | Fix ~3-5 emails/week | System is 85-90% accurate, less to fix |
| Month 3+ | Rarely fix anything | System is 90-95% accurate |

---

## Accuracy Evolution

| Timeline | Labeled Data | Active Layers | Expected Accuracy |
|----------|-------------|---------------|-------------------|
| **Day 1** | 0 examples | Rules only | 70–80% |
| **Week 1** | 10-30 corrections | Rules + Similarity | 80–85% |
| **Week 2-4** | 40-80 corrections | Rules + Similarity + SetFit | 85–90% |
| **Month 2+** | 100+ corrections | All layers, refined | 90–95% |

---

## Resource Summary

| Resource | Value |
|----------|-------|
| Total disk (models) | ~170MB (MiniLM 80MB + SetFit 90MB) |
| Runtime RAM | ~500MB |
| Peak RAM (during SetFit training) | ~2GB |
| GPU required | ❌ No |
| Internet required | Only once to download models, then fully offline |
| Total cost | **$0** |

## Dependencies

```
# ML & NLP
sentence-transformers>=2.2.0    # Sentence embeddings (MiniLM)
setfit>=1.0.0                   # Few-shot classification
scikit-learn>=1.3.0             # TF-IDF, LogisticRegression utilities
numpy>=1.24.0                   # Numerical operations

# PyTorch (CPU-only — no GPU bloat)
torch>=2.0.0                    # Install via: pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## What We Explicitly Chose NOT to Use

| Approach | Why Not |
|----------|---------|
| OpenAI / Claude API | Costs money, sends your emails to external servers |
| Local LLMs (Ollama) | Too slow for batch processing (5-15 sec/email), high RAM |
| BART-large-mnli | Too slow on CPU (2-5 sec/email), 4GB RAM |
| Fine-tuned transformer | Needs 2000+ examples, training takes hours on CPU |
| Cloud ML services | Costs money, privacy concerns |
