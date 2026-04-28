"""Local HMAC-verified webhook receiver for Zoom (closes #17).

Reference: https://developers.zoom.us/docs/api/webhooks/

How Zoom signs webhook deliveries (since 2023):

  X-Zm-Request-Timestamp: 1660157595650
  X-Zm-Signature: v0=<hex(hmac-sha256(SECRET_TOKEN, "v0:" + ts + ":" + body))>

The signature scheme is "v0:" — currently the only supported version.
Receivers must verify in constant time (``hmac.compare_digest``).

Endpoint validation: when you set up a new webhook in the Zoom Marketplace,
Zoom sends one POST with body
``{"event": "endpoint.url_validation", "payload": {"plainToken": "..."}}``
and expects ``{"plainToken": "...", "encryptedToken": "..."}`` back, where
``encryptedToken = hex(hmac-sha256(SECRET_TOKEN, plainToken))``. The CLI
``zoom webhook serve`` handles that handshake automatically.

This module is split:

  - **Crypto helpers** (pure, side-effect-free) — easily unit-tested:
      compute_signature(secret_token, timestamp, body) -> str
      verify_signature(secret_token, timestamp, body, signature) -> bool
      compute_url_validation_response(secret_token, plain_token) -> dict

  - **HTTP handler** (BaseHTTPRequestHandler subclass) — the receiver
    loop. Spawned by ``zoom webhook serve``.

The ``run_webhook_server`` entrypoint binds, prints the listen address,
and serves until interrupted (Ctrl-C). Each verified event is dumped to
stdout as JSON (one event per line for easy ``jq`` piping); failed
verifications get a 401 + a stderr line.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

#: Maximum age (seconds) for the X-Zm-Request-Timestamp before we reject
#: the request as a possible replay. 5 minutes matches Zoom's documented
#: tolerance and is short enough to limit the window of a stolen body.
MAX_TIMESTAMP_SKEW_SECONDS = 300

#: Currently the only signature scheme Zoom emits. Pinned so a future
#: scheme upgrade is a deliberate, reviewed change.
SIGNATURE_VERSION_PREFIX = "v0="


def compute_signature(secret_token: str, timestamp: str, body: bytes | str) -> str:
    """Return the ``X-Zm-Signature`` value for the given request.

    The body is mixed into the HMAC as bytes — never as the parsed
    JSON. Whitespace, key order, and trailing newlines all matter to
    the signature.
    """
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    msg = b"v0:" + timestamp.encode("ascii") + b":" + body_bytes
    digest = hmac.new(secret_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION_PREFIX}{digest}"


def verify_signature(
    secret_token: str,
    timestamp: str,
    body: bytes | str,
    signature: str,
) -> bool:
    """Constant-time HMAC verification of an incoming Zoom webhook.

    Returns ``True`` only if the signature matches exactly. Any tampering
    of the body, timestamp, or signature flips the result. Uses
    ``hmac.compare_digest`` to avoid timing leaks.
    """
    expected = compute_signature(secret_token, timestamp, body)
    return hmac.compare_digest(expected, signature)


def compute_url_validation_response(secret_token: str, plain_token: str) -> dict[str, str]:
    """Build the response body for Zoom's endpoint.url_validation handshake.

    Zoom sends ``{"plainToken": "..."}`` and expects back
    ``{"plainToken": "<echo>", "encryptedToken": "<hex(hmac)>"}``.
    """
    digest = hmac.new(
        secret_token.encode("utf-8"),
        plain_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": digest}


def _make_handler(secret_token: str, *, sink=None):
    """Build a :class:`BaseHTTPRequestHandler` subclass closed over
    ``secret_token``. ``sink`` is a callable taking the parsed event dict
    (default: dump as one-line JSON to stdout); useful for tests.
    """
    if sink is None:

        def sink(event: dict[str, Any]) -> None:
            sys.stdout.write(json.dumps(event) + "\n")
            sys.stdout.flush()

    class WebhookHandler(BaseHTTPRequestHandler):
        # POST is the only verb Zoom uses.
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            timestamp = self.headers.get("X-Zm-Request-Timestamp", "")
            signature = self.headers.get("X-Zm-Signature", "")

            # Endpoint URL validation: Zoom doesn't sign this handshake;
            # we recognise it by event name and respond synchronously.
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._respond(400, b'{"error":"invalid JSON body"}')
                return

            if payload.get("event") == "endpoint.url_validation":
                plain = payload.get("payload", {}).get("plainToken", "")
                response = compute_url_validation_response(secret_token, plain)
                self._respond(
                    200,
                    json.dumps(response).encode("utf-8"),
                    content_type="application/json",
                )
                return

            # Real event — must be signed.
            if not signature or not timestamp:
                self._respond(401, b'{"error":"missing signature headers"}')
                sys.stderr.write("webhook: rejected — missing signature headers\n")
                return

            if not verify_signature(secret_token, timestamp, body, signature):
                self._respond(401, b'{"error":"invalid signature"}')
                sys.stderr.write("webhook: rejected — invalid signature\n")
                return

            # Verified — surface the event.
            sink(payload)
            self._respond(200, b'{"status":"ok"}')

        def _respond(
            self,
            status: int,
            body: bytes,
            *,
            content_type: str = "application/json",
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Silence the default request log; structured output goes to
            # stdout via ``sink``.
            pass

    return WebhookHandler


def run_webhook_server(
    secret_token: str,
    *,
    bind: str = "127.0.0.1",
    port: int = 8000,
    sink=None,
    server_class=HTTPServer,
) -> None:
    """Bind and serve forever. Ctrl-C exits cleanly.

    ``server_class`` is injected for tests (e.g. a one-shot server). Tests
    typically poke the handler directly via :func:`_make_handler` instead.
    """
    handler_cls = _make_handler(secret_token, sink=sink)
    server = server_class((bind, port), handler_cls)
    bound_host, bound_port = server.server_address[:2]
    sys.stderr.write(f"Listening for Zoom webhooks on http://{bound_host}:{bound_port}/\n")
    sys.stderr.write("Configure your Zoom app's Event Subscription URL to point here.\n")
    sys.stderr.write("Press Ctrl-C to stop.\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nStopping.\n")
    finally:
        server.server_close()
