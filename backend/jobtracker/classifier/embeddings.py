"""
Sentence Embeddings Classifier (Layer 2)
========================================

Uses sentence-transformers with e5-small-v2 model to find similar emails
based on semantic similarity. This layer activates after the user has
corrected at least one email.

Embeddings are stored in SQLite (email_embeddings table) for persistence.
"""

import logging
from typing import Optional

import numpy as np

from jobtracker.database.models import EmailCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Embedding Model
# =============================================================================


class EmbeddingModel:
    """
    Sentence embedding model using e5-small-v2.

    Downloads ~80MB model on first use, then runs locally.
    Stores embeddings in SQLite for similarity search.
    """

    MODEL_NAME = "intfloat/e5-small-v2"
    MODEL_VERSION = "e5-small-v2"
    EMBEDDING_DIM = 384

    def __init__(self):
        self._model = None
        self._model_loaded = False

    def _load_model(self):
        """Lazy load the model on first use."""
        if self._model_loaded:
            return

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self.MODEL_NAME}")
            self._model = SentenceTransformer(self.MODEL_NAME)
            self._model_loaded = True
            logger.info("Embedding model loaded successfully")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
            self._model = None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._model = None

    def is_available(self) -> bool:
        """Check if the model is available."""
        if not self._model_loaded:
            self._load_model()
        return self._model is not None

    def encode(self, text: str) -> Optional[np.ndarray]:
        """
        Encode text into a 384-dimensional embedding.

        Uses the e5 prefix "query: " for best results.

        Args:
            text: Text to encode (subject + body)

        Returns:
            384-dimensional numpy array, or None if model unavailable
        """
        if not self.is_available():
            return None

        # e5 models work best with "query: " prefix for classification
        prefixed_text = f"query: {text}"

        try:
            embedding = self._model.encode(
                prefixed_text,
                convert_to_numpy=True,
                normalize_embeddings=True,  # L2 normalize for cosine similarity
            )
            return embedding.astype(np.float32)
        except Exception as e:
            logger.error(f"Failed to encode text: {e}")
            return None

    def encode_batch(self, texts: list[str]) -> Optional[np.ndarray]:
        """
        Encode multiple texts at once (more efficient).

        Args:
            texts: List of texts to encode

        Returns:
            2D numpy array of shape (len(texts), 384)
        """
        if not self.is_available() or not texts:
            return None

        # Add prefix to all texts
        prefixed_texts = [f"query: {t}" for t in texts]

        try:
            embeddings = self._model.encode(
                prefixed_texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 10,
            )
            return embeddings.astype(np.float32)
        except Exception as e:
            logger.error(f"Failed to encode batch: {e}")
            return None


# =============================================================================
# Embedding Storage (SQLite serialization)
# =============================================================================


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialize a numpy embedding to bytes for SQLite storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes from SQLite to numpy embedding."""
    return np.frombuffer(data, dtype=np.float32)


# =============================================================================
# Similarity Search
# =============================================================================


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two embeddings.

    Both embeddings should already be L2-normalized.
    """
    return float(np.dot(a, b))


def find_most_similar(
    query_embedding: np.ndarray,
    known_embeddings: list[tuple[np.ndarray, EmailCategory]],
    threshold: float = 0.85,
) -> Optional[tuple[EmailCategory, float]]:
    """
    Find the most similar known embedding to the query.

    Args:
        query_embedding: Embedding of the email to classify
        known_embeddings: List of (embedding, category) tuples
        threshold: Minimum similarity to consider a match

    Returns:
        (category, similarity_score) if match found, None otherwise
    """
    if not known_embeddings:
        return None

    best_category = None
    best_similarity = 0.0

    for known_emb, category in known_embeddings:
        similarity = cosine_similarity(query_embedding, known_emb)
        if similarity > best_similarity:
            best_similarity = similarity
            best_category = category

    if best_similarity >= threshold:
        return (best_category, best_similarity)

    return None


# =============================================================================
# Embedding Classifier
# =============================================================================


class EmbeddingsClassifier:
    """
    Classifier that uses sentence embeddings for similarity-based matching.

    Compares new emails against previously labeled examples stored in the database.
    """

    SIMILARITY_THRESHOLD = 0.85

    def __init__(self):
        self._model = EmbeddingModel()
        self._known_embeddings: list[tuple[np.ndarray, EmailCategory]] = []
        self._loaded = False

    def is_available(self) -> bool:
        """Check if the embedding model is available."""
        return self._model.is_available()

    async def load_known_embeddings(self):
        """Load all known embeddings from the database."""
        if self._loaded:
            return

        try:
            from sqlalchemy import select

            from jobtracker.database import get_session
            from jobtracker.database.models import EmailEmbedding

            self._known_embeddings = []

            async with get_session() as session:
                result = await session.exec(select(EmailEmbedding))
                embeddings = result.all()

                for row in embeddings:
                    # Extract from Row if needed
                    emb = row[0] if hasattr(row, "__getitem__") else row
                    if emb.embedding:
                        embedding_array = bytes_to_embedding(emb.embedding)
                        category = EmailCategory(emb.label)
                        self._known_embeddings.append((embedding_array, category))

            self._loaded = True
            logger.info(f"Loaded {len(self._known_embeddings)} known embeddings")

        except Exception as e:
            logger.error(f"Failed to load known embeddings: {e}")
            self._known_embeddings = []

    def has_known_examples(self) -> bool:
        """Check if there are any known examples for similarity matching."""
        return len(self._known_embeddings) > 0

    async def get_example_count(self) -> int:
        """Get count of embeddings from database (for status reporting)."""
        try:
            from sqlalchemy import func, select, text

            from jobtracker.database import get_session

            async with get_session() as session:
                # Use raw SQL for simple count to avoid ORM complexity
                result = await session.exec(
                    text("SELECT COUNT(*) FROM email_embeddings")
                )
                row = result.first()
                return row[0] if row else 0
        except Exception:
            return 0

    async def classify(
        self,
        subject: str,
        body: str,
    ) -> Optional[tuple[EmailCategory, float]]:
        """
        Classify an email using embedding similarity.

        Args:
            subject: Email subject
            body: Email body text

        Returns:
            (category, confidence) if similar example found, None otherwise
        """
        if not self.is_available():
            return None

        # Ensure known embeddings are loaded
        await self.load_known_embeddings()

        if not self.has_known_examples():
            return None

        # Create embedding for the email
        text = f"{subject}\n\n{body}"
        embedding = self._model.encode(text)

        if embedding is None:
            return None

        # Find most similar known example
        result = find_most_similar(
            embedding,
            self._known_embeddings,
            threshold=self.SIMILARITY_THRESHOLD,
        )

        return result

    async def add_example(
        self,
        email_id: int,
        subject: str,
        body: str,
        category: EmailCategory,
    ):
        """
        Add a new labeled example to the embeddings store.

        Called when user corrects a classification.

        Args:
            email_id: ID of the email
            subject: Email subject
            body: Email body
            category: Correct category (from user)
        """
        if not self.is_available():
            logger.warning("Cannot add example: embedding model not available")
            return

        # Create embedding
        text = f"{subject}\n\n{body}"
        embedding = self._model.encode(text)

        if embedding is None:
            return

        try:
            from sqlalchemy import select

            from jobtracker.database import get_session
            from jobtracker.database.models import EmailEmbedding

            async with get_session() as session:
                # Check if already exists
                result = await session.exec(
                    select(EmailEmbedding).where(EmailEmbedding.email_id == email_id)
                )
                existing = result.first()

                if existing:
                    # Update existing
                    emb = existing[0] if hasattr(existing, "__getitem__") else existing
                    emb.label = category.value
                    emb.embedding = embedding_to_bytes(embedding)
                    session.add(emb)
                else:
                    # Create new
                    new_embedding = EmailEmbedding(
                        email_id=email_id,
                        label=category.value,
                        embedding=embedding_to_bytes(embedding),
                        model_version=EmbeddingModel.MODEL_VERSION,
                    )
                    session.add(new_embedding)

                await session.commit()

            # Add to in-memory cache
            self._known_embeddings.append((embedding, category))
            logger.info(
                f"Added embedding for email {email_id} with label {category.value}"
            )

        except Exception as e:
            logger.error(f"Failed to save embedding: {e}")

    def reload(self):
        """Force reload of known embeddings on next classify call."""
        self._loaded = False
        self._known_embeddings = []


# =============================================================================
# Singleton Instance
# =============================================================================

_classifier: Optional[EmbeddingsClassifier] = None


def get_embeddings_classifier() -> EmbeddingsClassifier:
    """Get singleton embeddings classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = EmbeddingsClassifier()
    return _classifier
