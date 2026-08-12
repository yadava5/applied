"""
SetFit Few-Shot Classifier (Layer 3)
====================================

SetFit (Sentence Transformer Fine-tuning) trains a classifier from as few as
5-10 examples per category using contrastive learning.

This layer activates after the user has accumulated ~40+ corrections across
at least 3 categories.

Training happens in the background and takes 2-5 minutes on CPU.
"""

import asyncio
import json
import logging
import random
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from jobtracker.config import settings
from jobtracker.database.models import LOCAL_USER_ID, EmailCategory

if TYPE_CHECKING:  # pragma: no cover - types only
    from sqlmodel.ext.asyncio.session import AsyncSession

    from jobtracker.database.models import TrainingData

logger = logging.getLogger(__name__)

TRAINING_METADATA_SCHEMA_VERSION = 1
TRAINING_METADATA_SUPPORTED_SCHEMA_VERSIONS = {TRAINING_METADATA_SCHEMA_VERSION}


# =============================================================================
# One user per model — a Google Workspace API policy constraint, not a taste
# =============================================================================
#
# Applied reads mail through Gmail's **restricted** ``gmail.readonly`` scope.
# Google's Workspace API user-data policy permits using data obtained that way
# to "create, train, or improve a machine learning or artificial intelligence
# model" only where the model is personalized to that one end user — tailored
# to a single end user, with **no co-mingling of data across users**. Restricted
# scope verification (which is what lifts the 100-user OAuth test cap) is
# granted against exactly this policy, so a pooled model is not a quality
# problem, it is a breach that blocks verification.
#
# Desktop is single-user: every row carries the ``LOCAL_USER_ID`` sentinel and
# the auto-retrain loop is a legitimate personalized model. The hazard is the
# same code aimed at production Postgres, where a batch trainer connects as an
# admin role that RLS does not constrain and an unfiltered
# ``select(TrainingData)`` would quietly return every tenant's corrections.
#
# Two defences, deliberately redundant:
#   1. ``user_id`` is a *required keyword argument* on every training entry
#      point and becomes a ``WHERE`` clause on the corpus read.
#   2. The rows that actually came back are inspected, and anything owned by
#      another user raises. Derived from the data, not from a caller's promise.
#
# (2) is unreachable while (1) holds. That is the point: it is what catches the
# future refactor that deletes the ``WHERE`` as redundant, or a caller that
# passes the wrong id. Do not remove either half.


class CrossUserTrainingError(RuntimeError):
    """Raised when a training corpus contains rows owned by another user."""


def resolve_training_user_id() -> uuid.UUID:
    """The single user whose corrections the current context may train on.

    Cloud requests bind the verified JWT ``sub`` to a ContextVar; desktop and
    the local ML scripts have no authenticated identity and fall back to the
    ``LOCAL_USER_ID`` sentinel that every desktop row carries.

    The fallback is what makes a misdirected run safe rather than dangerous: a
    batch script pointed at production ``DATABASE_URL`` resolves to the
    sentinel, matches no production rows, and trains on nothing — instead of
    pooling every tenant's mail into one model.
    """

    from jobtracker.database import get_current_user_id

    return get_current_user_id() or LOCAL_USER_ID


def _validate_count_mapping(
    value: Any,
    *,
    field_name: str,
) -> dict[str, int]:
    """Validate a flat mapping of string keys to non-negative integer counts."""
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")

    normalized: dict[str, int] = {}
    for raw_key, raw_count in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError(f"{field_name} contains empty key")
        if not isinstance(raw_count, int) or isinstance(raw_count, bool):
            raise ValueError(f"{field_name}.{key} must be an integer")
        if raw_count < 0:
            raise ValueError(f"{field_name}.{key} must be >= 0")
        normalized[key] = int(raw_count)
    return normalized


def _validate_nested_count_mapping(
    value: Any,
    *,
    field_name: str,
) -> dict[str, dict[str, int]]:
    """Validate a nested mapping of label->source->count."""
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")

    normalized: dict[str, dict[str, int]] = {}
    for raw_label, raw_source_map in value.items():
        label = str(raw_label).strip()
        if not label:
            raise ValueError(f"{field_name} contains empty label key")
        normalized[label] = _validate_count_mapping(
            raw_source_map,
            field_name=f"{field_name}.{label}",
        )
    return normalized


def _validate_label_to_id_mapping(value: Any) -> dict[str, int]:
    """Validate label->id mapping."""
    if not isinstance(value, dict):
        raise ValueError("label_to_id must be an object")

    normalized: dict[str, int] = {}
    for raw_label, raw_id in value.items():
        label = str(raw_label).strip()
        if not label:
            raise ValueError("label_to_id contains empty label")
        if not isinstance(raw_id, int) or isinstance(raw_id, bool):
            raise ValueError(f"label_to_id.{label} must be an integer")
        if raw_id < 0:
            raise ValueError(f"label_to_id.{label} must be >= 0")
        normalized[label] = int(raw_id)
    return normalized


def _validate_id_to_label_mapping(value: Any) -> dict[int, str]:
    """Validate id->label mapping with numeric-string keys from JSON."""
    if not isinstance(value, dict):
        raise ValueError("id_to_label must be an object")

    normalized: dict[int, str] = {}
    for raw_id, raw_label in value.items():
        key = str(raw_id).strip()
        if not key.isdigit():
            raise ValueError(f"id_to_label key '{raw_id}' must be a non-negative integer string")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError(f"id_to_label.{key} must be a non-empty string")
        normalized[int(key)] = raw_label.strip()
    return normalized


def validate_training_metadata_contract(
    metadata: dict[str, Any],
    *,
    allow_legacy_without_schema_version: bool = False,
) -> None:
    """
    Validate the strict training metadata provenance contract.

    Raises ValueError when metadata is missing required fields or contains
    inconsistent values.
    """
    if not isinstance(metadata, dict):
        raise ValueError("training metadata must be an object")

    schema_version = metadata.get("schema_version")
    if schema_version is None:
        if not allow_legacy_without_schema_version:
            raise ValueError("schema_version is required")
    else:
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise ValueError("schema_version must be an integer")
        if schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        if schema_version not in TRAINING_METADATA_SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                "unsupported schema_version; update compatibility checks before loading this artifact"
            )

    trained_at = metadata.get("trained_at")
    if not isinstance(trained_at, str) or not trained_at.strip():
        raise ValueError("trained_at must be a non-empty string")
    try:
        datetime.fromisoformat(trained_at)
    except ValueError as exc:
        raise ValueError("trained_at must be ISO-8601 compatible") from exc

    base_model = metadata.get("base_model")
    if not isinstance(base_model, str) or not base_model.strip():
        raise ValueError("base_model must be a non-empty string")

    scalar_int_fields = (
        "total_examples",
        "train_split_size",
        "eval_split_size",
        "max_saved_models",
    )
    scalar_values: dict[str, int] = {}
    for field_name in scalar_int_fields:
        raw_value = metadata.get(field_name)
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise ValueError(f"{field_name} must be an integer")
        if raw_value < 0:
            raise ValueError(f"{field_name} must be >= 0")
        scalar_values[field_name] = int(raw_value)

    if scalar_values["max_saved_models"] <= 0:
        raise ValueError("max_saved_models must be > 0")

    label_counts = _validate_count_mapping(
        metadata.get("label_counts"),
        field_name="label_counts",
    )
    source_counts = _validate_count_mapping(
        metadata.get("source_counts"),
        field_name="source_counts",
    )
    label_source_counts = _validate_nested_count_mapping(
        metadata.get("label_source_counts"),
        field_name="label_source_counts",
    )
    label_to_id = _validate_label_to_id_mapping(metadata.get("label_to_id"))
    id_to_label = _validate_id_to_label_mapping(metadata.get("id_to_label"))

    total_examples = scalar_values["total_examples"]
    if sum(label_counts.values()) != total_examples:
        raise ValueError("sum(label_counts) must equal total_examples")
    if sum(source_counts.values()) != total_examples:
        raise ValueError("sum(source_counts) must equal total_examples")
    if scalar_values["train_split_size"] + scalar_values["eval_split_size"] != total_examples:
        raise ValueError("train_split_size + eval_split_size must equal total_examples")

    label_keys = set(label_counts.keys())
    if set(label_source_counts.keys()) != label_keys:
        raise ValueError("label_source_counts keys must exactly match label_counts keys")
    if set(label_to_id.keys()) != label_keys:
        raise ValueError("label_to_id keys must exactly match label_counts keys")

    for label, counts_by_source in label_source_counts.items():
        if sum(counts_by_source.values()) != label_counts[label]:
            raise ValueError(
                f"sum(label_source_counts.{label}) must equal label_counts.{label}"
            )

    rolled_up_source_counts: Counter[str] = Counter()
    for counts_by_source in label_source_counts.values():
        for source, count in counts_by_source.items():
            rolled_up_source_counts[source] += count
    if dict(sorted(rolled_up_source_counts.items())) != dict(sorted(source_counts.items())):
        raise ValueError(
            "source_counts must equal the sum of label_source_counts across all labels"
        )

    derived_id_to_label = {idx: label for label, idx in label_to_id.items()}
    if derived_id_to_label != id_to_label:
        raise ValueError("label_to_id and id_to_label must be exact inverses")


# =============================================================================
# Model Paths
# =============================================================================


def get_models_dir() -> Path:
    """Get the directory for storing SetFit models."""
    # Use the same directory as the database
    models_dir = Path(settings.database_dir).expanduser() / "models" / "setfit"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_latest_model_path() -> Optional[Path]:
    """Get the path to the latest trained model."""
    models_dir = get_models_dir()
    model_dirs = sorted(
        [d for d in models_dir.iterdir() if d.is_dir()],
        reverse=True,
    )
    return model_dirs[0] if model_dirs else None


# =============================================================================
# SetFit Classifier
# =============================================================================


class SetFitClassifier:
    """
    Few-shot classifier using SetFit.

    Trains on user-corrected examples stored in the training_data table.
    Retrains automatically when enough new corrections accumulate.
    """

    MIN_EXAMPLES_PER_CATEGORY = 5
    MIN_CATEGORIES = 3
    MIN_TOTAL_EXAMPLES = 40
    MAX_SAVED_MODELS = 3
    MAX_EXAMPLES_PER_LABEL_FOR_TRAINING = 24
    SOURCE_PRIORITY = (
        "user_correction",
        "external_dataset",
        "mock_seed_v3",
        "mock_seed_v2",
        "mock_seed",
        "bulk_import",
    )
    SOURCE_TARGET_PER_LABEL = {
        "user_correction": 12,
        "external_dataset": 8,
        "mock_seed_v3": 8,
        "mock_seed_v2": 8,
        "mock_seed": 4,
        "bulk_import": 8,
    }

    def __init__(self):
        self._model = None
        self._model_loaded = False
        self._is_training = False
        self._label_to_category: dict[int, str] = {}
        self._category_to_label: dict[str, int] = {}
        self._last_training_source_counts: dict[str, int] = {}
        self._last_training_label_source_counts: dict[str, dict[str, int]] = {}

    def _load_model(self):
        """Load the latest trained model if available."""
        if self._model_loaded:
            return

        model_path = get_latest_model_path()
        if model_path is None:
            logger.info("No trained SetFit model found")
            return

        try:
            from setfit import SetFitModel

            logger.info(f"Loading SetFit model from: {model_path}")
            self._model = SetFitModel.from_pretrained(str(model_path))
            self._model_loaded = True

            # Load label mapping
            label_map_path = model_path / "label_mapping.txt"
            if label_map_path.exists():
                with open(label_map_path) as f:
                    for line in f:
                        idx, category = line.strip().split(":")
                        self._label_to_category[int(idx)] = category
                        self._category_to_label[category] = int(idx)

            logger.info("SetFit model loaded successfully")

        except ImportError:
            logger.warning("setfit not installed. Run: pip install setfit")
        except Exception as e:
            logger.error(f"Failed to load SetFit model: {e}")

    def is_available(self) -> bool:
        """Check if a trained model is available."""
        if not self._model_loaded:
            self._load_model()
        return self._model is not None

    def is_training(self) -> bool:
        """Check if training is currently in progress."""
        return self._is_training

    def classify(
        self,
        subject: str,
        body: str,
    ) -> Optional[tuple[EmailCategory, float]]:
        """
        Classify an email using the SetFit model.

        Args:
            subject: Email subject
            body: Email body text

        Returns:
            (category, confidence) if model available, None otherwise
        """
        if not self.is_available():
            return None

        text = f"{subject}\n\n{body}"

        try:
            # Get prediction
            predictions = self._model.predict([text])
            predicted_value = predictions[0]

            # Get probabilities if available
            try:
                probs = self._model.predict_proba([text])
                confidence = float(probs[0].max())
            except Exception:
                # Fallback confidence
                confidence = 0.75

            category = self._resolve_predicted_category(predicted_value)
            if category is None:
                return None

            return (category, confidence)

        except Exception as e:
            logger.error(f"SetFit prediction failed: {e}")
            return None

    def _resolve_predicted_category(self, predicted_value: Any) -> Optional[EmailCategory]:
        """
        Resolve SetFit output into an EmailCategory.

        Some SetFit versions return integer label IDs while others return
        string labels. We support both formats for compatibility.
        """
        if isinstance(predicted_value, EmailCategory):
            return predicted_value

        # Direct string label output (common in some SetFit versions)
        if isinstance(predicted_value, str):
            normalized = predicted_value.strip()

            if normalized in self._category_to_label:
                return EmailCategory(normalized)

            if normalized in {category.value for category in EmailCategory}:
                return EmailCategory(normalized)

            if normalized.isdigit():
                category_name = self._label_to_category.get(int(normalized))
                if category_name is not None:
                    return EmailCategory(category_name)

            return None

        # Numeric label output
        if isinstance(predicted_value, (int, float)):
            category_name = self._label_to_category.get(int(predicted_value))
            if category_name is None:
                return None
            return EmailCategory(category_name)

        return None

    async def should_retrain(self, *, user_id: uuid.UUID) -> bool:
        """
        Check if we have enough new training data to retrain.

        Conditions:
        - At least MIN_TOTAL_EXAMPLES total corrections **for this user**
        - At least MIN_CATEGORIES with MIN_EXAMPLES_PER_CATEGORY each
        - Not currently training

        Args:
            user_id: The single user whose corrections are counted. Required —
                the thresholds decide whether to train, so counting another
                user's rows here would trip a training run that is only ever
                allowed to read one user's data. See ``CrossUserTrainingError``.
        """
        if self._is_training:
            return False

        try:
            from sqlalchemy import func, select

            from jobtracker.database import get_session
            from jobtracker.database.models import TrainingData

            async with get_session() as session:
                # Count examples per category, for THIS USER ONLY: the counts
                # gate a training run, and that run may only ever see one
                # user's corrections (gmail.readonly restricted-scope policy).
                result = await session.exec(
                    select(
                        TrainingData.label,
                        func.count(TrainingData.id).label("count"),
                    )
                    .where(TrainingData.user_id == user_id)
                    .group_by(TrainingData.label)
                )
                category_counts = {row[0]: row[1] for row in result.all()}

                total = sum(category_counts.values())
                categories_with_enough = sum(
                    1
                    for count in category_counts.values()
                    if count >= self.MIN_EXAMPLES_PER_CATEGORY
                )

                should_train = (
                    total >= self.MIN_TOTAL_EXAMPLES
                    and categories_with_enough >= self.MIN_CATEGORIES
                )

                if should_train:
                    logger.info(
                        f"Training data ready: {total} examples across "
                        f"{categories_with_enough} categories with "
                        f">= {self.MIN_EXAMPLES_PER_CATEGORY} examples"
                    )

                return should_train

        except Exception as e:
            logger.error(f"Failed to check training data: {e}")
            return False

    async def train(self, *, user_id: uuid.UUID):
        """
        Train the SetFit model on one user's corrections.

        Runs in background (non-blocking).

        Args:
            user_id: The single user whose corrections form the corpus.
                Required, and not defaulted: a model trained on Gmail data may
                only be personalized to one end user (see the module header),
                so there is no sensible "all users" value to fall back to.
                Local/desktop callers pass ``resolve_training_user_id()``.

        Raises:
            CrossUserTrainingError: if the loaded corpus contains rows owned by
                anyone other than ``user_id``. Deliberately propagates past the
                catch-all below — a policy breach must stop the run, not land
                in a log line nobody reads.
        """
        if self._is_training:
            logger.warning("Training already in progress")
            return

        self._is_training = True
        logger.info("Starting SetFit training for user %s...", user_id)

        try:
            # Get training data
            training_texts, training_labels = await self._get_training_data(user_id=user_id)

            if not training_texts:
                logger.warning("No training data available")
                return

            # Run training in thread pool (CPU-bound)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._train_sync,
                training_texts,
                training_labels,
            )

            # Reload the new model
            self._model_loaded = False
            self._load_model()

            logger.info("SetFit training completed successfully")

        except CrossUserTrainingError:
            # Never demote a policy violation to a log line: the caller
            # (POST /classify/retrain, scripts/ml_cycle.sh --retrain) has to
            # see this fail.
            raise
        except Exception as e:
            logger.error(f"SetFit training failed: {e}")
        finally:
            self._is_training = False

    async def _load_training_rows(
        self,
        session: "AsyncSession",
        *,
        user_id: uuid.UUID,
    ) -> list["TrainingData"]:
        """Read the training corpus for exactly one user.

        The ``WHERE`` clause is the whole point of this method existing
        separately — keep the read in one place so there is one thing to audit.
        """

        from sqlalchemy import select

        from jobtracker.database.models import TrainingData

        result = await session.exec(
            select(TrainingData).where(TrainingData.user_id == user_id)
        )
        return [row[0] if hasattr(row, "__getitem__") else row for row in result.all()]

    @staticmethod
    def _assert_single_user_corpus(
        rows: "list[TrainingData]",
        *,
        user_id: uuid.UUID,
    ) -> None:
        """Refuse a corpus that contains anyone but ``user_id``.

        Derived from the rows that actually came back, not from the caller's
        promise — this is what still catches the bug if the ``WHERE`` clause in
        :meth:`_load_training_rows` is ever dropped, or if a caller passes an
        id that does not match what it loaded.
        """

        foreign = {row.user_id for row in rows if row.user_id != user_id}
        if not foreign:
            return

        raise CrossUserTrainingError(
            "Refusing to train on a corpus that spans users. Applied reads mail "
            "under Gmail's restricted gmail.readonly scope, and Google's "
            "Workspace API user-data policy allows that data to train only a "
            "model personalized to one end user, with no co-mingling across "
            "users; a pooled model would also fail restricted-scope "
            f"verification. Requested user_id={user_id}, but the corpus also "
            f"contains {sorted(str(other) for other in foreign)}. Train one "
            "user at a time (see resolve_training_user_id())."
        )

    async def _get_training_data(self, *, user_id: uuid.UUID) -> tuple[list[str], list[str]]:
        """Get one user's training data from the database.

        Args:
            user_id: The only user whose rows may enter the corpus.

        Raises:
            CrossUserTrainingError: if any loaded row belongs to another user.
        """
        try:
            from jobtracker.database import get_session

            texts: list[str] = []
            labels: list[str] = []
            rng = random.Random(42)
            source_counts: Counter[str] = Counter()
            label_source_counts: dict[str, Counter[str]] = {}

            async with get_session() as session:
                examples = await self._load_training_rows(session, user_id=user_id)

                # Checked on the raw rows, BEFORE any are dropped below —
                # a foreign user whose rows are all ``needs_review`` would
                # otherwise slip past unnoticed.
                self._assert_single_user_corpus(examples, user_id=user_id)

                by_label_source: dict[str, dict[str, list[str]]] = {}
                for data in examples:
                    # Combine subject and body
                    text = f"{data.subject or ''}\n\n{data.body_text or ''}"
                    label = str(data.label)
                    if label == EmailCategory.NEEDS_REVIEW.value:
                        continue
                    source = str(data.source or "unknown")
                    by_label_source.setdefault(label, {}).setdefault(source, []).append(text)

                for source_map in by_label_source.values():
                    for items in source_map.values():
                        rng.shuffle(items)

                for label in sorted(by_label_source.keys()):
                    selected_texts: list[str] = []
                    selected_sources: list[str] = []
                    source_map = by_label_source[label]
                    taken_per_source: dict[str, int] = {
                        source: 0 for source in source_map.keys()
                    }

                    for source in self.SOURCE_PRIORITY:
                        if source not in source_map:
                            continue
                        remaining = self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING - len(selected_texts)
                        if remaining <= 0:
                            break
                        cap = self.SOURCE_TARGET_PER_LABEL.get(
                            source,
                            self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING,
                        )
                        take = min(remaining, cap, len(source_map[source]))
                        if take <= 0:
                            continue
                        selected_texts.extend(source_map[source][:take])
                        selected_sources.extend([source] * take)
                        taken_per_source[source] += take

                    if len(selected_texts) < self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING:
                        source_order = list(self.SOURCE_PRIORITY) + [
                            source
                            for source in sorted(source_map.keys())
                            if source not in self.SOURCE_PRIORITY
                        ]
                        while len(selected_texts) < self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING:
                            added = False
                            for source in source_order:
                                if source not in source_map:
                                    continue
                                idx = taken_per_source.get(source, 0)
                                if idx >= len(source_map[source]):
                                    continue
                                selected_texts.append(source_map[source][idx])
                                selected_sources.append(source)
                                taken_per_source[source] = idx + 1
                                added = True
                                if (
                                    len(selected_texts)
                                    >= self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING
                                ):
                                    break
                            if not added:
                                break

                    label_counter = label_source_counts.setdefault(label, Counter())

                    for item_text, item_source in zip(selected_texts, selected_sources):
                        texts.append(item_text)
                        labels.append(label)
                        source_counts[item_source] += 1
                        label_counter[item_source] += 1

                self._last_training_source_counts = dict(sorted(source_counts.items()))
                self._last_training_label_source_counts = {
                    label: dict(sorted(counter.items()))
                    for label, counter in sorted(label_source_counts.items())
                }

                logger.info(
                    "Prepared balanced SetFit training set: %d examples (%d labels, max %d/label)",
                    len(labels),
                    len(set(labels)),
                    self.MAX_EXAMPLES_PER_LABEL_FOR_TRAINING,
                )

            return texts, labels

        except CrossUserTrainingError:
            # See ``train``: this one is never logged-and-swallowed. Returning
            # ``[], []`` here would turn a policy breach into a silent no-op.
            raise
        except Exception as e:
            logger.error(f"Failed to get training data: {e}")
            return [], []

    def _train_sync(self, texts: list[str], labels: list[str]):
        """Synchronous training (runs in thread pool)."""
        try:
            from setfit import SetFitModel, Trainer, TrainingArguments
            from datasets import Dataset

            # Create label mapping
            unique_labels = sorted(set(labels))
            self._label_to_category = {i: label for i, label in enumerate(unique_labels)}
            self._category_to_label = {label: i for i, label in enumerate(unique_labels)}

            # Convert labels to integers
            int_labels = [self._category_to_label[label] for label in labels]

            # Create dataset
            dataset = Dataset.from_dict({"text": texts, "label": int_labels})

            # Split for training/eval (90/10)
            dataset = dataset.train_test_split(test_size=0.1, seed=42)

            # Initialize model
            model = SetFitModel.from_pretrained(
                "sentence-transformers/paraphrase-MiniLM-L6-v2",
                labels=unique_labels,
            )

            # Training arguments
            args = TrainingArguments(
                batch_size=16,
                num_epochs=1,
                evaluation_strategy="epoch",
                save_strategy="epoch",
                load_best_model_at_end=True,
            )

            # Create trainer
            trainer = Trainer(
                model=model,
                args=args,
                train_dataset=dataset["train"],
                eval_dataset=dataset["test"],
            )

            # Train
            trainer.train()

            # Save model
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_path = get_models_dir() / f"setfit_model_{timestamp}"
            model.save_pretrained(str(model_path))

            # Save label mapping
            with open(model_path / "label_mapping.txt", "w") as f:
                for idx, label in self._label_to_category.items():
                    f.write(f"{idx}:{label}\n")

            self._write_training_metadata(model_path, labels, dataset)

            logger.info(f"Model saved to: {model_path}")

            # Cleanup old models
            self._cleanup_old_models()

        except ImportError as e:
            logger.error(f"Missing dependency for SetFit training: {e}")
        except Exception as e:
            logger.error(f"Training failed: {e}")
            raise

    def _cleanup_old_models(self):
        """Remove old models, keeping only the most recent ones."""
        models_dir = get_models_dir()
        model_dirs = sorted(
            [d for d in models_dir.iterdir() if d.is_dir()],
            reverse=True,
        )

        # Keep only MAX_SAVED_MODELS
        for old_model in model_dirs[self.MAX_SAVED_MODELS :]:
            try:
                import shutil

                shutil.rmtree(old_model)
                logger.info(f"Removed old model: {old_model}")
            except Exception as e:
                logger.warning(f"Failed to remove old model {old_model}: {e}")

    def _write_training_metadata(self, model_path: Path, labels: list[str], dataset) -> None:
        """Persist training provenance metadata with the saved model."""
        label_counts = Counter(labels)
        metadata = {
            "schema_version": TRAINING_METADATA_SCHEMA_VERSION,
            "trained_at": datetime.utcnow().isoformat(),
            "base_model": "sentence-transformers/paraphrase-MiniLM-L6-v2",
            "total_examples": len(labels),
            "label_counts": dict(sorted(label_counts.items())),
            "source_counts": self._last_training_source_counts,
            "label_source_counts": self._last_training_label_source_counts,
            "label_to_id": self._category_to_label,
            "id_to_label": self._label_to_category,
            "train_split_size": len(dataset["train"]),
            "eval_split_size": len(dataset["test"]),
            "max_saved_models": self.MAX_SAVED_MODELS,
        }
        validate_training_metadata_contract(metadata)
        with open(model_path / "training_metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, sort_keys=True)

    def reload(self):
        """Force reload of model on next use."""
        self._model = None
        self._model_loaded = False


# =============================================================================
# Singleton Instance
# =============================================================================

_classifier: Optional[SetFitClassifier] = None


def get_setfit_classifier() -> SetFitClassifier:
    """Get singleton SetFit classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = SetFitClassifier()
    return _classifier
