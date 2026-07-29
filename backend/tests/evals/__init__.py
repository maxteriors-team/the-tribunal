"""Model-in-the-loop evaluation suites.

Evals call real LLM APIs, so they cost money and are non-deterministic. They
are marked ``@pytest.mark.eval`` and excluded from the default pytest run
(and therefore from ``make ci.backend``). Run them on demand with::

    uv run pytest tests/evals -m eval -s
"""
