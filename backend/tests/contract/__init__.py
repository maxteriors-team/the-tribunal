"""Webhook contract tests.

End-to-end tests that load real-shape, sanitized webhook payloads from
``tests/contract/fixtures/`` (Telnyx voice + SMS and Resend email events), sign
them with deterministic test credentials, and POST them
to the actual webhook router endpoints under a FastAPI test app.

Each test asserts:

1. The HTTP boundary returns ``200`` (the router accepts the verified
   payload and never propagates a 4xx/5xx for a well-formed signed body).
2. The expected downstream side effect fires — per-event handler invoked
   with the parsed payload, Resend ``handle_event`` invoked with the
   ``svix-id`` as the idempotency key, etc.

These tests are *contract* tests: they pin the wire-format shape of each
fixture against the router + signature-verification stack as it exists
today. If a provider changes a field name, the relevant fixture should be updated
to match production traffic and these tests will continue to enforce
that the router parses it correctly.
"""
