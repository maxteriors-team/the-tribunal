"""IVR loop detection using TF-IDF transcript similarity."""

from typing import Any

import structlog

logger = structlog.get_logger()


class LoopDetector:
    """Detects repeating IVR menus using TF-IDF similarity.

    IVR systems often repeat the same menu when no input is received.
    This detector identifies such loops to trigger alternative actions
    like pressing "0" for operator.

    Uses sklearn TfidfVectorizer when available, falls back to Jaccard
    similarity for environments without sklearn.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        max_history: int = 10,
    ) -> None:
        """Initialize loop detector.

        Args:
            similarity_threshold: Minimum similarity score to consider a loop (0.0-1.0)
            max_history: Maximum transcripts to keep in history
        """
        self.similarity_threshold = similarity_threshold
        self.max_history = max_history
        self._transcripts: list[str] = []
        self._vectorizer: Any | None = None
        self.logger = logger.bind(service="loop_detector")
        self._use_sklearn = self._init_sklearn()

    def _init_sklearn(self) -> bool:
        """Initialize sklearn TfidfVectorizer if available.

        Returns:
            True if sklearn is available, False otherwise
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity  # noqa: F401

            self._vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),  # Unigrams and bigrams
                stop_words="english",
                max_features=100,
            )
            self.logger.info("loop_detector_using_sklearn")
            return True
        except ImportError:
            self.logger.info("loop_detector_using_fallback_jaccard")
            return False

    def add_transcript(self, transcript: str) -> None:
        """Add a transcript to the history.

        Args:
            transcript: Transcript text to add
        """
        if not transcript or len(transcript.strip()) < 10:
            return

        self._transcripts.append(transcript.lower().strip())

        # Keep history bounded
        if len(self._transcripts) > self.max_history:
            self._transcripts.pop(0)

    def is_loop_detected(self) -> bool:
        """Check if the recent transcripts indicate a loop.

        Returns:
            True if a loop is detected (same IVR menu repeated)
        """
        if len(self._transcripts) < 2:
            return False

        # Compare most recent transcript to previous ones
        recent = self._transcripts[-1]

        for i in range(len(self._transcripts) - 2, -1, -1):
            previous = self._transcripts[i]
            similarity = self._calculate_similarity(recent, previous)

            if similarity >= self.similarity_threshold:
                self.logger.info(
                    "ivr_loop_detected",
                    similarity=similarity,
                    threshold=self.similarity_threshold,
                    recent_preview=recent[:50],
                    previous_preview=previous[:50],
                )
                return True

        return False

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two transcripts.

        Uses TF-IDF cosine similarity if sklearn available,
        otherwise falls back to Jaccard similarity.

        Args:
            text1: First transcript
            text2: Second transcript

        Returns:
            Similarity score between 0.0 and 1.0
        """
        if self._use_sklearn:
            return self._tfidf_similarity(text1, text2)
        return self._jaccard_similarity(text1, text2)

    def _tfidf_similarity(self, text1: str, text2: str) -> float:
        """Calculate TF-IDF cosine similarity.

        Args:
            text1: First transcript
            text2: Second transcript

        Returns:
            Cosine similarity score
        """
        try:
            from sklearn.metrics.pairwise import cosine_similarity

            if self._vectorizer is None:
                return self._jaccard_similarity(text1, text2)

            # Fit and transform both texts
            tfidf_matrix = self._vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])
            return float(similarity[0][0])
        except Exception as e:
            self.logger.warning("tfidf_similarity_error", error=str(e))
            return self._jaccard_similarity(text1, text2)

    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """Calculate Jaccard similarity (fallback method).

        Args:
            text1: First transcript
            text2: Second transcript

        Returns:
            Jaccard similarity score
        """
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def reset(self) -> None:
        """Clear transcript history."""
        self._transcripts.clear()
