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
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from jobtracker.config import settings
from jobtracker.database.models import EmailCategory

logger = logging.getLogger(__name__)


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

    def __init__(self):
        self._model = None
        self._model_loaded = False
        self._is_training = False
        self._label_to_category: dict[int, str] = {}
        self._category_to_label: dict[str, int] = {}

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
            pred_label = int(predictions[0])

            # Get probabilities if available
            try:
                probs = self._model.predict_proba([text])
                confidence = float(probs[0].max())
            except Exception:
                # Fallback confidence
                confidence = 0.75

            # Map label to category
            category_name = self._label_to_category.get(pred_label)
            if category_name is None:
                return None

            category = EmailCategory(category_name)
            return (category, confidence)

        except Exception as e:
            logger.error(f"SetFit prediction failed: {e}")
            return None

    async def should_retrain(self) -> bool:
        """
        Check if we have enough new training data to retrain.

        Conditions:
        - At least MIN_TOTAL_EXAMPLES total corrections
        - At least MIN_CATEGORIES with MIN_EXAMPLES_PER_CATEGORY each
        - Not currently training
        """
        if self._is_training:
            return False

        try:
            from sqlalchemy import func, select

            from jobtracker.database import get_session
            from jobtracker.database.models import TrainingData

            async with get_session() as session:
                # Count examples per category
                result = await session.exec(
                    select(
                        TrainingData.label,
                        func.count(TrainingData.id).label("count"),
                    ).group_by(TrainingData.label)
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

    async def train(self):
        """
        Train the SetFit model on user corrections.

        Runs in background (non-blocking).
        """
        if self._is_training:
            logger.warning("Training already in progress")
            return

        self._is_training = True
        logger.info("Starting SetFit training...")

        try:
            # Get training data
            training_texts, training_labels = await self._get_training_data()

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

        except Exception as e:
            logger.error(f"SetFit training failed: {e}")
        finally:
            self._is_training = False

    async def _get_training_data(self) -> tuple[list[str], list[str]]:
        """Get training data from the database."""
        try:
            from sqlalchemy import select

            from jobtracker.database import get_session
            from jobtracker.database.models import TrainingData

            texts = []
            labels = []

            async with get_session() as session:
                result = await session.exec(select(TrainingData))
                examples = result.all()

                for row in examples:
                    data = row[0] if hasattr(row, "__getitem__") else row
                    # Combine subject and body
                    text = f"{data.subject or ''}\n\n{data.body_text or ''}"
                    texts.append(text)
                    labels.append(data.label)

            return texts, labels

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
