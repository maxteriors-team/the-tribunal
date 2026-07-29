"""Tests for the token-aware recursive chunker.

Locks in the three properties the ingestion pipeline relies on:

* **Offset fidelity** — ``content == text[char_start:char_end]`` for every chunk,
  offsets are in-bounds and non-decreasing, so callers can cite source passages.
* **Token budgeting** — chunks respect the target token ceiling and the splitter
  prefers coarse (paragraph) separators over fine (word/char) ones.
* **Overlap** — consecutive chunks share trailing context.

A deterministic word-count token counter is injected so the tests never depend
on tiktoken (and never need network access to fetch its BPE table).
"""

from __future__ import annotations

from app.services.knowledge.chunking import (
    TextChunk,
    chunk_text,
    default_token_counter,
)


def _words(text: str) -> int:
    """Deterministic, network-free token counter: one token per whitespace word."""
    return len(text.split())


class TestOffsets:
    def test_content_matches_offsets_exactly(self) -> None:
        text = "Para one sentence here.\n\nPara two has more words than one.\n\nPara three."
        chunks = chunk_text(text, target_tokens=6, overlap_tokens=2, count_tokens=_words)
        assert chunks
        for chunk in chunks:
            assert chunk.content == text[chunk.char_start : chunk.char_end]
            assert 0 <= chunk.char_start < chunk.char_end <= len(text)

    def test_ordinals_are_sequential_from_zero(self) -> None:
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
        chunks = chunk_text(text, target_tokens=4, overlap_tokens=1, count_tokens=_words)
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))

    def test_starts_are_non_decreasing(self) -> None:
        text = "\n\n".join(f"paragraph number {i} with several words" for i in range(8))
        chunks = chunk_text(text, target_tokens=8, overlap_tokens=3, count_tokens=_words)
        starts = [c.char_start for c in chunks]
        assert starts == sorted(starts)

    def test_content_is_whitespace_trimmed(self) -> None:
        text = "first block here.\n\n\n   second block padded.   \n\n third block."
        chunks = chunk_text(text, target_tokens=4, overlap_tokens=1, count_tokens=_words)
        for chunk in chunks:
            assert chunk.content == chunk.content.strip()


class TestBudgeting:
    def test_empty_and_whitespace_yield_no_chunks(self) -> None:
        assert chunk_text("", count_tokens=_words) == []
        assert chunk_text("   \n\n  \t ", count_tokens=_words) == []

    def test_short_text_is_a_single_chunk(self) -> None:
        text = "just a few words"
        chunks = chunk_text(text, target_tokens=400, overlap_tokens=80, count_tokens=_words)
        assert len(chunks) == 1
        assert chunks[0] == TextChunk(
            ordinal=0,
            content=text,
            char_start=0,
            char_end=len(text),
            token_count=4,
        )

    def test_chunks_respect_token_target_when_splittable(self) -> None:
        # 30 single-word "paragraphs"; with target 5 each chunk holds <= 5 words.
        text = "\n\n".join(f"w{i}" for i in range(30))
        chunks = chunk_text(text, target_tokens=5, overlap_tokens=0, count_tokens=_words)
        assert len(chunks) > 1
        for chunk in chunks:
            assert _words(chunk.content) <= 5

    def test_prefers_paragraph_break_over_word_break(self) -> None:
        # Two paragraphs that each fit the budget should split on the blank line.
        text = "alpha beta gamma\n\ndelta epsilon zeta"
        chunks = chunk_text(text, target_tokens=3, overlap_tokens=0, count_tokens=_words)
        contents = [c.content for c in chunks]
        assert "alpha beta gamma" in contents
        assert "delta epsilon zeta" in contents

    def test_separator_free_run_is_hard_split(self) -> None:
        # No whitespace at all: falls through to the character-window terminal split.
        # A char-length counter forces the oversized, separator-free run to split.
        text = "x" * 5000
        chunks = chunk_text(text, target_tokens=50, overlap_tokens=0, count_tokens=len)
        assert len(chunks) > 1
        # Reassembling the (non-overlapping) windows reproduces the source.
        assert "".join(c.content for c in chunks) == text


class TestOverlap:
    def test_consecutive_chunks_overlap(self) -> None:
        text = " ".join(f"token{i}" for i in range(40))
        chunks = chunk_text(text, target_tokens=8, overlap_tokens=3, count_tokens=_words)
        assert len(chunks) >= 2
        # With overlap, a later chunk starts before the previous chunk ends.
        assert any(chunks[i + 1].char_start < chunks[i].char_end for i in range(len(chunks) - 1))

    def test_zero_overlap_chunks_do_not_share_text(self) -> None:
        text = " ".join(f"token{i}" for i in range(40))
        chunks = chunk_text(text, target_tokens=8, overlap_tokens=0, count_tokens=_words)
        for i in range(len(chunks) - 1):
            assert chunks[i + 1].char_start >= chunks[i].char_end


class TestValidation:
    def test_rejects_non_positive_target(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            chunk_text("hi", target_tokens=0, count_tokens=_words)

    def test_rejects_overlap_ge_target(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            chunk_text("hi", target_tokens=5, overlap_tokens=5, count_tokens=_words)


class TestDefaultTokenCounter:
    def test_counts_tokens_for_real_text(self) -> None:
        # Whatever backend resolves (tiktoken or heuristic), a non-trivial string
        # must count as a positive number of tokens, and empty as zero.
        assert default_token_counter("") == 0
        assert default_token_counter("hello world this is a sentence") > 0
