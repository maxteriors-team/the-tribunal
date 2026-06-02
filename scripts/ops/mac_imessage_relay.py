#!/usr/bin/env python3
"""Self-hosted Mac relay for Messages.app/iMessage via the imsg CLI.

Run on a Mac signed in to Messages.app. Expose it only over localhost, a
private network, or Tailscale; do not place it directly on the public internet.

Smoke test:
    MAC_RELAY_TOKEN=local-token python scripts/mac_imessage_relay.py serve
    curl -H 'Authorization: Bearer local-token' \
      -H 'Content-Type: application/json' \
      -d '{"to":"+14155551212","text":"hello","service":"imessage"}' \
      http://127.0.0.1:8765/v1/messages

Watch inbound events:
    MAC_RELAY_BACKEND_WEBHOOK_URL=https://api.example.com/webhooks/mac-relay/messages \
    MAC_RELAY_BACKEND_WEBHOOK_TOKEN=backend-token \
      python scripts/mac_imessage_relay.py watch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

_ALLOWED_SERVICES = {"imessage", "sms", "auto"}
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_MAX_BODY_BYTES = 64 * 1024
_E164ISH_RE = re.compile(r"^\+[1-9]\d{6,14}$")


@dataclass(slots=True, frozen=True)
class RelayConfig:
    """Runtime configuration for the relay HTTP server and watcher."""

    token: str
    backend_webhook_url: str
    backend_webhook_token: str
    imsg_path: str
    default_service: str


class RelayRequestHandler(BaseHTTPRequestHandler):
    """Tiny JSON HTTP API for sending messages through imsg."""

    server_version = "MacIMessageRelay/1.0"
    config: RelayConfig

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/messages":
            self._handle_send_message()
            return
        if self.path == "/v1/webhooks/test":
            self._handle_webhook_test()
            return
        self._send_json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _handle_send_message(self) -> None:
        if not self._authorized(self.config.token):
            self._send_json(401, {"error": "unauthorized"})
            return

        payload = self._read_json()
        if payload is None:
            return

        to = _string_value(payload.get("to"))
        text = _string_value(payload.get("text"))
        sender = _string_value(payload.get("from"))
        service = _string_value(payload.get("service")) or self.config.default_service
        client_message_id = _string_value(payload.get("client_message_id")) or str(uuid.uuid4())

        if not _E164ISH_RE.match(to):
            self._send_json(400, {"error": "invalid_recipient"})
            return
        if not text:
            self._send_json(400, {"error": "missing_text"})
            return
        if service not in _ALLOWED_SERVICES:
            self._send_json(400, {"error": "invalid_service"})
            return

        command = [
            self.config.imsg_path,
            "send",
            "--to",
            to,
            "--text",
            text,
            "--service",
            service,
            "--json",
        ]
        started = time.monotonic()
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raw_stdout = result.stdout.strip()
        raw_stderr = result.stderr.strip()
        raw_json = _parse_json_line(raw_stdout)

        if result.returncode != 0:
            self._send_json(
                502,
                {
                    "id": client_message_id,
                    "status": "failed",
                    "exit_code": result.returncode,
                    "stderr": raw_stderr,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return

        self._send_json(
            200,
            {
                "id": _message_id_from_imsg(raw_json) or client_message_id,
                "status": "sent",
                "client_message_id": client_message_id,
                "to": to,
                "from": sender,
                "service": service,
                "raw": raw_json or raw_stdout,
                "stderr": raw_stderr,
                "elapsed_ms": elapsed_ms,
            },
        )

    def _handle_webhook_test(self) -> None:
        if not self._authorized(self.config.token):
            self._send_json(401, {"error": "unauthorized"})
            return
        if not self.config.backend_webhook_url:
            self._send_json(400, {"error": "backend_webhook_url_not_configured"})
            return
        event = {
            "event_id": f"relay-test-{uuid.uuid4()}",
            "message_id": f"relay-test-{uuid.uuid4()}",
            "from": "+14155552671",
            "to": "+12125550101",
            "text": "Mac relay webhook test",
            "created_at": _now_iso(),
            "is_from_me": False,
            "service": "imessage",
        }
        status, body = post_backend_webhook(
            self.config.backend_webhook_url,
            self.config.backend_webhook_token,
            event,
        )
        self._send_json(status if status < 500 else 502, {"backend_status": status, "body": body})

    def _read_json(self) -> dict[str, Any] | None:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0 or content_length > _MAX_BODY_BYTES:
            self._send_json(413, {"error": "invalid_body_size"})
            return None
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "json_object_required"})
            return None
        return payload

    def _authorized(self, expected_token: str) -> bool:
        scheme, _, token = self.headers.get("Authorization", "").partition(" ")
        return bool(expected_token and scheme.lower() == "bearer" and token == expected_token)

    def _send_json(self, status_code: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def serve(args: argparse.Namespace) -> None:
    """Run the local relay HTTP server."""
    config = _config_from_args(args)
    if not config.token:
        raise SystemExit("MAC_RELAY_TOKEN or --token is required")

    handler = type("ConfiguredRelayRequestHandler", (RelayRequestHandler,), {"config": config})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"mac relay listening on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", file=sys.stderr)
    finally:
        server.server_close()


def watch(args: argparse.Namespace) -> None:
    """Stream imsg watch --json and forward inbound events to the backend."""
    config = _config_from_args(args)
    if not config.backend_webhook_url:
        raise SystemExit("MAC_RELAY_BACKEND_WEBHOOK_URL or --backend-webhook-url is required")
    if not config.backend_webhook_token:
        raise SystemExit("MAC_RELAY_BACKEND_WEBHOOK_TOKEN/--backend-webhook-token is required")

    command = [config.imsg_path, "watch", "--json"]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    try:
        for line in process.stdout:
            event = _parse_json_line(line.strip())
            if not event:
                continue
            if bool(event.get("is_from_me", False)):
                continue
            status, body = post_backend_webhook(
                config.backend_webhook_url,
                config.backend_webhook_token,
                _normalize_watch_event(event),
            )
            print(
                json.dumps(
                    {"backend_status": status, "body": body, "guid": event.get("guid")},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
    finally:
        process.terminate()
        process.wait(timeout=5)


def post_backend_webhook(url: str, token: str, payload: dict[str, Any]) -> tuple[int, str]:
    """POST a relay event to the backend webhook."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return 0, "invalid webhook URL"

    connection_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    connection = connection_cls(parsed.netloc, timeout=30)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        return response.status, response_body
    finally:
        connection.close()


def _config_from_args(args: argparse.Namespace) -> RelayConfig:
    return RelayConfig(
        token=args.token or os.environ.get("MAC_RELAY_TOKEN", ""),
        backend_webhook_url=args.backend_webhook_url
        or os.environ.get("MAC_RELAY_BACKEND_WEBHOOK_URL", ""),
        backend_webhook_token=args.backend_webhook_token
        or os.environ.get("MAC_RELAY_BACKEND_WEBHOOK_TOKEN", "")
        or os.environ.get("MAC_RELAY_WEBHOOK_TOKEN", "")
        or os.environ.get("MAC_RELAY_TOKEN", ""),
        imsg_path=args.imsg_path or os.environ.get("IMSG_PATH", "imsg"),
        default_service=args.default_service or os.environ.get("MAC_RELAY_DEFAULT_SERVICE", "imessage"),
    )


def _normalize_watch_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event.get("guid") or event.get("id") or uuid.uuid4()),
        "message_id": str(event.get("guid") or event.get("id") or uuid.uuid4()),
        "guid": event.get("guid"),
        "from": event.get("sender") or event.get("from") or "",
        "to": event.get("destination_caller_id") or event.get("to") or "",
        "text": event.get("text") or "",
        "created_at": event.get("created_at") or _now_iso(),
        "is_from_me": bool(event.get("is_from_me", False)),
        "service": event.get("service") or "imessage",
        "chat_guid": event.get("chat_guid"),
    }


def _parse_json_line(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _message_id_from_imsg(raw: dict[str, Any] | None) -> str | None:
    if not raw:
        return None
    for key in ("guid", "message_id", "id"):
        value = raw.get(key)
        if isinstance(value, str | int) and str(value):
            return str(value)
    return None


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Mac iMessage relay around imsg")
    parser.add_argument("--token", default="", help="Bearer token for local relay API")
    parser.add_argument("--backend-webhook-url", default="", help="Backend /webhooks/mac-relay/messages URL")
    parser.add_argument("--backend-webhook-token", default="", help="Bearer token for backend webhook")
    parser.add_argument("--imsg-path", default="", help="Path to imsg binary")
    parser.add_argument(
        "--default-service",
        default="",
        choices=sorted(_ALLOWED_SERVICES),
        help="Default imsg service mode",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve", help="Run the local HTTP relay")
    serve_parser.add_argument("--host", default=_DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    serve_parser.set_defaults(func=serve)

    watch_parser = subparsers.add_parser("watch", help="Forward imsg watch --json events")
    watch_parser.set_defaults(func=watch)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
