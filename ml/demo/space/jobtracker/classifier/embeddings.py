"""
Sentence Embeddings Classifier (Layer 2)
========================================

Uses sentence-transformers with e5-small-v2 model to find similar emails
based on semantic similarity. This layer activates after the user has
corrected at least one email.

Embeddings are stored in SQLite (email_embeddings table) for persistence.
"""

import logging
import uuid
from typing import Optional

import numpy as np

from jobtracker.config import settings
from jobtracker.database.models import LOCAL_USER_ID, EmailCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Ownership
# =============================================================================
#
# Every row in ``email_embeddings`` belongs to exactly one user, and this layer
# may only ever see one user's rows at a time. Two defences, mirroring the ones
# ``setfit_model.py`` already applies to layer 3:
#
#   1. The corpus read carries a ``WHERE user_id = ...``.
#   2. The loaded rows are re-checked against the requested owner, derived from
#      the rows themselves rather than from a caller's promise, so a refactor
#      that deletes the ``WHERE`` as "redundant" fails loudly instead of
#      silently pooling tenants.
#
# Defence 2 is unreachable while defence 1 holds — that is the point of belt
# and braces. Postgres RLS is a third layer underneath both, but it cannot
# help here: the in-memory cache below serves later requests without issuing a
# query at all, so no policy is ever evaluated. Scoping has to be stated in
# this file.


class CrossUserEmbeddingError(RuntimeError):
    """Raised when a loaded corpus contains rows owned by more than one user."""


def resolve_embedding_user_id() -> uuid.UUID:
    """Owner whose examples this layer may read and write, for this request.

    Reads the RLS identity bound by the cloud auth dependency (see
    ``database.connection.set_current_user_id``) and falls back to the
    ``LOCAL_USER_ID`` sentinel that every desktop row carries. Deliberately a
    three-line twin of ``setfit_model.resolve_training_user_id`` rather than a
    shared import: ``setfit_model`` pulls torch, and the cloud import graph
    must never reach it from here.
    """

    from jobtracker.database import get_current_user_id

    return get_current_user_id() or LOCAL_USER_ID


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

            logger.info(
                "Embedding model strategy: %s",
                settings.ml_model_delivery_strategy,
            )
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
        # WHOSE examples ``_known_embeddings`` currently holds. This instance is
        # a process-global singleton (see ``get_embeddings_classifier``), so a
        # bare ``_loaded`` boolean meant the first request to warm the cache
        # answered every later request in the same process — including
        # requests from a different user. The cache is keyed by owner instead.
        self._loaded_user_id: Optional[uuid.UUID] = None
        # Set by ``pin_empty_corpus`` for the evaluation harness only.
        self._pinned = False

    def is_available(self) -> bool:
        """Check if the embedding model is available."""
        return self._model.is_available()

    async def _load_rows(self, session, *, user_id: uuid.UUID) -> list:
        """Read exactly one owner's stored examples.

        Split out from :meth:`load_known_embeddings` so the ownership check
        there can be exercised the way a dropped ``WHERE`` would present.
        """

        from sqlalchemy import select

        from jobtracker.database.models import EmailEmbedding

        result = await session.exec(
            select(EmailEmbedding).where(EmailEmbedding.user_id == user_id)
        )
        # ``exec`` yields Row tuples for a SQLAlchemy select, model instances
        # for a SQLModel one. Normalise so the ownership check can read
        # ``.user_id`` either way.
        return [row[0] if hasattr(row, "__getitem__") else row for row in result.all()]

    @staticmethod
    def _assert_single_user_corpus(rows: list, *, user_id: uuid.UUID) -> None:
        """Refuse a corpus that contains anyone but ``user_id``."""

        foreign = {row.user_id for row in rows if row.user_id != user_id}
        if not foreign:
            return
        raise CrossUserEmbeddingError(
            "Embedding corpus is not single-user: requested "
            f"user_id={user_id}, but it also contains {sorted(map(str, foreign))}. "
            "Layer 2 may only ever compare against the caller's own examples."
        )

    async def load_known_embeddings(self, *, user_id: Optional[uuid.UUID] = None):
        """Load one user's known embeddings from the database.

        Args:
            user_id: Whose examples to load. Defaults to the identity bound to
                the current request; there is deliberately no "all users"
                value.
        """
        if self._pinned:
            return

        target = user_id or resolve_embedding_user_id()

        if self._loaded and self._loaded_user_id == target:
            return

        try:
            from jobtracker.database import get_session

            self._known_embeddings = []
            self._loaded = False
            self._loaded_user_id = None

            async with get_session() as session:
                rows = await self._load_rows(session, user_id=target)
                self._assert_single_user_corpus(rows, user_id=target)

                for emb in rows:
                    if emb.embedding:
                        embedding_array = bytes_to_embedding(emb.embedding)
                        category = EmailCategory(emb.label)
                        self._known_embeddings.append((embedding_array, category))

            self._loaded = True
            self._loaded_user_id = target
            logger.info(
                "Loaded %d known embeddings for user %s",
                len(self._known_embeddings),
                target,
            )

        except CrossUserEmbeddingError:
            # Must escape the catch-all below: a corpus that pools tenants is
            # not a degraded classification, it is a bug that has to be seen.
            self._known_embeddings = []
            raise
        except Exception as e:
            logger.error(f"Failed to load known embeddings: {e}")
            self._known_embeddings = []

    def has_known_examples(self) -> bool:
        """Check if there are any known examples for similarity matching."""
        return len(self._known_embeddings) > 0

    async def get_example_count(self, *, user_id: Optional[uuid.UUID] = None) -> int:
        """Count one user's stored embeddings (for status reporting).

        Scoped like every other read here. The previous raw
        ``SELECT COUNT(*) FROM email_embeddings`` reported the whole table,
        which on a multi-tenant database is another user's row count.
        """
        target = user_id or resolve_embedding_user_id()
        try:
            from sqlalchemy import func, select

            from jobtracker.database import get_session
            from jobtracker.database.models import EmailEmbedding

            async with get_session() as session:
                result = await session.exec(
                    select(func.count())
                    .select_from(EmailEmbedding)
                    .where(EmailEmbedding.user_id == target)
                )
                row = result.first()
                if row is None:
                    return 0
                return int(row[0] if hasattr(row, "__getitem__") else row)
        except Exception:
            return 0

    async def classify(
        self,
        subject: str,
        body: str,
        *,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[tuple[EmailCategory, float]]:
        """
        Classify an email using embedding similarity.

        Args:
            subject: Email subject
            body: Email body text
            user_id: Whose examples may be compared against. Defaults to the
                identity bound to the current request.

        Returns:
            (category, confidence) if similar example found, None otherwise
        """
        if not self.is_available():
            return None

        target = user_id or resolve_embedding_user_id()

        # Ensure this user's known embeddings are loaded
        await self.load_known_embeddings(user_id=target)

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
        *,
        user_id: Optional[uuid.UUID] = None,
    ):
        """
        Add a new labeled example to the embeddings store.

        Called when user corrects a classification.

        Args:
            email_id: ID of the email
            subject: Email subject
            body: Email body
            category: Correct category (from user)
            user_id: Who made the correction. Defaults to the identity bound
                to the current request. Scoping the reads without stamping
                this would be worse than the leak it fixes — every correction
                would land on ``LOCAL_USER_ID`` and real users would then
                match against an empty corpus forever.
        """
        if not self.is_available():
            logger.warning("Cannot add example: embedding model not available")
            return

        target = user_id or resolve_embedding_user_id()

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
                # Check if already exists — for this owner. ``email_id`` is
                # globally unique today, but matching on it alone would let a
                # correction silently overwrite a row it does not own if that
                # ever stops being true.
                result = await session.exec(
                    select(EmailEmbedding).where(
                        EmailEmbedding.user_id == target,
                        EmailEmbedding.email_id == email_id,
                    )
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
                        user_id=target,
                        email_id=email_id,
                        label=category.value,
                        embedding=embedding_to_bytes(embedding),
                        model_version=EmbeddingModel.MODEL_VERSION,
                    )
                    session.add(new_embedding)

                await session.commit()

            # Add to the in-memory cache only when it already holds THIS
            # owner's corpus. Appending into a cache warmed by someone else is
            # the write-side version of the leak this scoping exists to close.
            if self._loaded and self._loaded_user_id == target:
                self._known_embeddings.append((embedding, category))
            logger.info(
                "Added embedding for email %s with label %s (user %s)",
                email_id,
                category.value,
                target,
            )

        except Exception as e:
            logger.error(f"Failed to save embedding: {e}")

    def pin_empty_corpus(self) -> None:
        """Serve no examples to anyone until :meth:`reload` is called.

        The evaluation harness's ``deterministic`` profile needs layer 2 to
        contribute nothing, so a benchmark score never depends on whatever
        happens to be in the local database. It used to express that by
        setting ``_loaded = True`` with an empty list; now that the load
        short-circuit is keyed by owner, that would no longer hold for a
        caller whose identity differs from the cached one. Say it explicitly
        instead of relying on the shape of the cache key.
        """
        self._known_embeddings = []
        self._loaded = True
        self._loaded_user_id = None
        self._pinned = True

    def reload(self):
        """Force reload of known embeddings on next classify call."""
        self._loaded = False
        self._loaded_user_id = None
        self._pinned = False
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
