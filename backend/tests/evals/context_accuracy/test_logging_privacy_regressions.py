"""Source-level guards against reintroducing body/PII fields into AI logs."""

from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("relative_path", "forbidden_snippets"),
    [
        (
            "app/services/ai/text_tool_executor.py",
            ("arguments=arguments", "result=result"),
        ),
        (
            "app/services/ai/tool_executor.py",
            ("arguments=arguments", "result=result"),
        ),
        (
            "app/services/ai/grok/session.py",
            ("arguments=arguments_str", "message_preview="),
        ),
        (
            "app/services/ai/grok/audio_stream.py",
            ("message_preview=",),
        ),
        (
            "app/services/ai/voice_agent.py",
            ("message_preview=",),
        ),
        (
            "app/services/ai/opt_out_detector.py",
            ("message_preview=",),
        ),
    ],
)
def test_ai_logging_paths_do_not_emit_raw_bodies_or_tool_payloads(
    relative_path: str,
    forbidden_snippets: tuple[str, ...],
) -> None:
    source = (_BACKEND_ROOT / relative_path).read_text()

    for snippet in forbidden_snippets:
        assert snippet not in source
