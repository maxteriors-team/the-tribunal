"""Chaos tests — fault injection on external service clients.

Each test mounts an ``httpx.MockTransport`` that intentionally misbehaves
(random 500s, latency, timeouts) and asserts the production retry/circuit-
breaker policy holds up. Run with::

    cd backend && uv run pytest tests/chaos -v
"""
