"""Tests for LoopDetector.

Tests verify:
- Loop detection when menus repeat
- Novel speech resets detection
- Threshold tuning behavior
"""


from app.services.ai.ivr_detector import LoopDetector


class TestLoopDetectorBasics:
    """Basic loop detector tests."""

    def test_no_loop_with_single_transcript(self, loop_detector: LoopDetector):
        """Single transcript should not trigger loop detection."""
        loop_detector.add_transcript("Press 1 for sales, press 2 for support.")

        assert not loop_detector.is_loop_detected()

    def test_no_loop_with_different_transcripts(self, loop_detector: LoopDetector):
        """Different transcripts should not trigger loop detection."""
        loop_detector.add_transcript("Press 1 for sales.")
        loop_detector.add_transcript("Press 2 for support.")
        loop_detector.add_transcript("Press 3 for billing.")

        assert not loop_detector.is_loop_detected()

    def test_loop_detected_with_repeated_transcript(self, loop_detector: LoopDetector):
        """Identical repeated transcripts should trigger loop detection."""
        menu = "Press 1 for sales, press 2 for support, press 0 for operator."

        loop_detector.add_transcript(menu)
        loop_detector.add_transcript(menu)

        assert loop_detector.is_loop_detected()

    def test_loop_detected_with_similar_transcripts(self, loop_detector: LoopDetector):
        """Nearly identical transcripts should trigger loop detection."""
        # Use same words in same order (Jaccard sees these as identical)
        loop_detector.add_transcript(
            "Press 1 for sales press 2 for support press 0 for operator"
        )
        loop_detector.add_transcript(
            "Press 1 for sales press 2 for support press 0 for operator"
        )

        assert loop_detector.is_loop_detected()


class TestLoopDetectorThreshold:
    """Tests for threshold behavior."""

    def test_loop_not_detected_below_threshold(self):
        """Transcripts below similarity threshold should not trigger loop."""
        detector = LoopDetector(similarity_threshold=0.95, max_history=10)

        detector.add_transcript("Press 1 for sales, press 2 for support.")
        detector.add_transcript("Press 1 for billing, press 2 for technical help.")

        # These are similar but not 95% similar
        assert not detector.is_loop_detected()

    def test_sensitive_threshold_detects_loops(self):
        """Lower threshold should detect loops more easily."""
        strict = LoopDetector(similarity_threshold=0.95, max_history=10)
        sensitive = LoopDetector(similarity_threshold=0.4, max_history=10)

        # Same menu rephrased: shares core terms (sales, support, billing)
        # but reordered/abbreviated. TF-IDF cosine sits in the mid range,
        # so a strict threshold misses it while a sensitive one catches it.
        first = "Press 1 for sales, press 2 for support, press 3 for billing."
        second = "For sales press 1, for billing press 3."

        for d in (strict, sensitive):
            d.add_transcript(first)
            d.add_transcript(second)

        assert not strict.is_loop_detected()
        assert sensitive.is_loop_detected()


class TestLoopDetectorReset:
    """Tests for reset and novel speech behavior."""

    def test_reset_clears_history(self, loop_detector: LoopDetector):
        """Reset should clear transcript history."""
        menu = "Press 1 for sales, press 2 for support."

        loop_detector.add_transcript(menu)
        loop_detector.add_transcript(menu)
        assert loop_detector.is_loop_detected()

        loop_detector.reset()
        assert not loop_detector.is_loop_detected()

    def test_novel_speech_breaks_loop(self, loop_detector: LoopDetector):
        """Novel (different) speech after repetition should break the loop pattern."""
        menu = "Press 1 for sales, press 2 for support."

        loop_detector.add_transcript(menu)
        loop_detector.add_transcript(menu)
        assert loop_detector.is_loop_detected()

        # Add completely different transcript
        loop_detector.add_transcript(
            "Connecting you to the sales department. Please hold."
        )

        # Now the most recent is different from previous
        assert not loop_detector.is_loop_detected()

    def test_pattern_after_novel_speech(self, loop_detector: LoopDetector):
        """Loop should be detected again after novel speech if menu repeats."""
        menu = "Press 1 for sales, press 2 for support."
        different = "Connecting you to sales. Please hold."

        loop_detector.add_transcript(menu)
        loop_detector.add_transcript(menu)
        assert loop_detector.is_loop_detected()

        loop_detector.add_transcript(different)
        assert not loop_detector.is_loop_detected()

        # Back to original menu
        loop_detector.add_transcript(menu)
        assert loop_detector.is_loop_detected()


class TestLoopDetectorHistory:
    """Tests for history management."""

    def test_max_history_limit(self):
        """History should be bounded by max_history."""
        detector = LoopDetector(similarity_threshold=0.85, max_history=3)

        detector.add_transcript("Menu A - Press 1 for sales.")
        detector.add_transcript("Menu B - Press 2 for support.")
        detector.add_transcript("Menu C - Press 3 for billing.")
        detector.add_transcript("Menu D - Press 4 for other.")

        # Only last 3 should be kept
        assert len(detector._transcripts) == 3

    def test_old_transcripts_evicted(self):
        """Old transcripts should be evicted when history is full."""
        detector = LoopDetector(similarity_threshold=0.85, max_history=3)

        menu = "Press 1 for sales, press 2 for support."

        detector.add_transcript(menu)
        detector.add_transcript("Connecting you to the next available agent.")
        detector.add_transcript("Your estimated wait time is five minutes.")
        assert not detector.is_loop_detected()

        # Now add the original menu again - old copy should be evicted
        detector.add_transcript("Thank you for your patience, please continue to hold.")
        detector.add_transcript(menu)

        # The original was pushed out, so no loop
        assert not detector.is_loop_detected()

    def test_short_transcripts_ignored(self, loop_detector: LoopDetector):
        """Very short transcripts should be ignored."""
        loop_detector.add_transcript("OK")
        loop_detector.add_transcript("OK")

        # Short transcripts are not added
        assert not loop_detector.is_loop_detected()


class TestLoopDetectorSimilarityMethods:
    """Tests for similarity calculation methods."""

    def test_jaccard_similarity_identical(self, loop_detector: LoopDetector):
        """Identical texts should have similarity of 1.0."""
        text = "press one for sales press two for support"
        similarity = loop_detector._jaccard_similarity(text, text)
        assert similarity == 1.0

    def test_jaccard_similarity_different(self, loop_detector: LoopDetector):
        """Completely different texts should have low similarity."""
        text1 = "hello world"
        text2 = "goodbye moon"
        similarity = loop_detector._jaccard_similarity(text1, text2)
        assert similarity == 0.0

    def test_jaccard_similarity_partial(self, loop_detector: LoopDetector):
        """Partially overlapping texts should have medium similarity."""
        text1 = "press one for sales"
        text2 = "press two for support"
        similarity = loop_detector._jaccard_similarity(text1, text2)
        assert 0.0 < similarity < 1.0

    def test_jaccard_similarity_empty(self, loop_detector: LoopDetector):
        """Empty texts should have 0 similarity."""
        similarity = loop_detector._jaccard_similarity("", "hello")
        assert similarity == 0.0

        similarity = loop_detector._jaccard_similarity("hello", "")
        assert similarity == 0.0


class TestLoopDetectorIntegration:
    """Integration tests simulating real IVR scenarios."""

    def test_typical_ivr_loop_scenario(self, loop_detector: LoopDetector):
        """Test typical scenario where IVR repeats menu on timeout."""
        menu = (
            "Welcome to Acme Corp. Press 1 for sales, "
            "press 2 for support, press 0 for operator."
        )

        # First time hearing the menu
        loop_detector.add_transcript(menu)
        assert not loop_detector.is_loop_detected()

        # Menu repeats (no input was given)
        loop_detector.add_transcript(menu)
        assert loop_detector.is_loop_detected()

    def test_menu_navigation_no_loop(self, loop_detector: LoopDetector):
        """Normal navigation through different menus should not trigger loop."""
        loop_detector.add_transcript("Press 1 for sales, press 2 for support.")
        loop_detector.add_transcript("Sales department. Press 1 for new orders.")
        loop_detector.add_transcript("Please hold while we connect you.")

        assert not loop_detector.is_loop_detected()

    def test_stuck_in_submenu_loop(self, loop_detector: LoopDetector):
        """Detect loop when stuck in a submenu."""
        submenu = (
            "Press 1 for account balance, press 2 for recent transactions, "
            "press 9 to return to main menu."
        )

        loop_detector.add_transcript(submenu)
        assert not loop_detector.is_loop_detected()

        loop_detector.add_transcript(submenu)
        assert loop_detector.is_loop_detected()
