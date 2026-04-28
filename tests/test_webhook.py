"""Tests for zoom_cli.api.webhook — HMAC-verified webhook receiver."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from http.client import HTTPConnection
from threading import Thread

import pytest
from zoom_cli.api import webhook

# ---- crypto primitives (pure) ------------------------------------------


def test_compute_signature_format() -> None:
    """Signature is ``v0=<64-char-hex>`` per Zoom's published format."""
    sig = webhook.compute_signature("secret", "1660157595650", b'{"foo":"bar"}')
    assert sig.startswith("v0=")
    digest = sig[len("v0=") :]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_compute_signature_matches_zoom_documented_formula() -> None:
    """Pin the exact HMAC algorithm against an independent computation."""
    secret = "topsecret"
    timestamp = "1660157595650"
    body = b'{"event":"meeting.started","payload":{}}'

    expected_msg = b"v0:" + timestamp.encode("ascii") + b":" + body
    expected_digest = hmac.new(secret.encode("utf-8"), expected_msg, hashlib.sha256).hexdigest()
    expected = f"v0={expected_digest}"

    assert webhook.compute_signature(secret, timestamp, body) == expected


def test_compute_signature_accepts_str_or_bytes_body() -> None:
    sig_bytes = webhook.compute_signature("s", "t", b'{"x":1}')
    sig_str = webhook.compute_signature("s", "t", '{"x":1}')
    assert sig_bytes == sig_str


def test_compute_signature_changes_with_any_input() -> None:
    """Tampering with any of {secret, timestamp, body} flips the signature."""
    base = webhook.compute_signature("s1", "t1", b"body")
    assert webhook.compute_signature("s2", "t1", b"body") != base
    assert webhook.compute_signature("s1", "t2", b"body") != base
    assert webhook.compute_signature("s1", "t1", b"different") != base


def test_verify_signature_accepts_valid() -> None:
    sig = webhook.compute_signature("secret", "1234", b"hello")
    assert webhook.verify_signature("secret", "1234", b"hello", sig) is True


def test_verify_signature_rejects_tampering() -> None:
    sig = webhook.compute_signature("secret", "1234", b"hello")
    assert webhook.verify_signature("secret", "1234", b"different", sig) is False
    assert webhook.verify_signature("secret", "9999", b"hello", sig) is False
    assert webhook.verify_signature("wrong", "1234", b"hello", sig) is False


def test_verify_signature_rejects_truncated_signature() -> None:
    sig = webhook.compute_signature("s", "t", b"body")
    assert webhook.verify_signature("s", "t", b"body", sig[:-1]) is False


def test_compute_url_validation_response_format() -> None:
    """The handshake response is ``{plainToken, encryptedToken: hex(hmac)}``."""
    resp = webhook.compute_url_validation_response("secret", "abc-plain-token")

    assert resp["plainToken"] == "abc-plain-token"
    expected = hmac.new(b"secret", b"abc-plain-token", hashlib.sha256).hexdigest()
    assert resp["encryptedToken"] == expected


def test_url_validation_response_does_not_include_signature_prefix() -> None:
    """Unlike X-Zm-Signature, the handshake response is bare hex (no v0=)."""
    resp = webhook.compute_url_validation_response("s", "p")
    assert not resp["encryptedToken"].startswith("v0=")


# ---- module constants pinned ------------------------------------------


def test_signature_version_prefix_pinned() -> None:
    assert webhook.SIGNATURE_VERSION_PREFIX == "v0="


def test_max_timestamp_skew_pinned() -> None:
    """5 minutes matches Zoom's documented tolerance."""
    assert webhook.MAX_TIMESTAMP_SKEW_SECONDS == 300


# ---- HTTP handler (integration with a real loopback server) ------------


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture
def webhook_server():
    """Spin up a real ``HTTPServer`` on an ephemeral loopback port and
    yield (port, captured_events) for the test. Server thread is shut
    down on teardown."""
    from http.server import HTTPServer

    captured: list[dict] = []
    secret = "test-secret"
    handler_cls = webhook._make_handler(secret, sink=captured.append)

    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield secret, port, captured
    finally:
        server.shutdown()
        server.server_close()


def _post(port: int, body: bytes, headers: dict[str, str] | None = None):
    conn = HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        "/",
        body=body,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, payload


def test_handler_responds_to_url_validation_handshake(webhook_server) -> None:
    """First handshake is unsigned; we recognise it by event name."""
    secret, port, captured = webhook_server
    body = json.dumps(
        {"event": "endpoint.url_validation", "payload": {"plainToken": "abc"}}
    ).encode()

    status, response = _post(port, body)

    assert status == 200
    parsed = json.loads(response)
    assert parsed["plainToken"] == "abc"
    expected = hmac.new(secret.encode(), b"abc", hashlib.sha256).hexdigest()
    assert parsed["encryptedToken"] == expected
    # url_validation is NOT a real event — sink should not be invoked.
    assert captured == []


def test_handler_accepts_valid_signed_event(webhook_server) -> None:
    secret, port, captured = webhook_server
    body = json.dumps({"event": "meeting.started", "payload": {"foo": "bar"}}).encode()
    timestamp = "1660157595650"
    sig = webhook.compute_signature(secret, timestamp, body)

    status, _ = _post(
        port,
        body,
        headers={"X-Zm-Request-Timestamp": timestamp, "X-Zm-Signature": sig},
    )

    assert status == 200
    assert len(captured) == 1
    assert captured[0]["event"] == "meeting.started"


def test_handler_rejects_invalid_signature(webhook_server) -> None:
    _secret, port, captured = webhook_server
    body = b'{"event":"meeting.started","payload":{}}'
    status, response = _post(
        port,
        body,
        headers={
            "X-Zm-Request-Timestamp": "1234",
            "X-Zm-Signature": "v0=" + "0" * 64,  # wrong hex
        },
    )

    assert status == 401
    assert b"invalid signature" in response
    assert captured == []  # sink never invoked on rejected events


def test_handler_rejects_missing_signature_headers(webhook_server) -> None:
    _secret, port, captured = webhook_server
    status, response = _post(port, b'{"event":"meeting.started","payload":{}}')

    assert status == 401
    assert b"missing signature headers" in response
    assert captured == []


def test_handler_rejects_invalid_json_body(webhook_server) -> None:
    _secret, port, captured = webhook_server
    status, response = _post(port, b"not json at all")

    assert status == 400
    assert b"invalid JSON body" in response
    assert captured == []


def test_handler_rejects_tampered_body_after_signature(webhook_server) -> None:
    """Sign one body, send a different one — must be rejected. Pins the
    integrity guarantee against a man-in-the-middle who changes the body
    in flight."""
    secret, port, captured = webhook_server
    original = b'{"event":"meeting.started","payload":{"foo":"bar"}}'
    timestamp = "1234"
    sig = webhook.compute_signature(secret, timestamp, original)

    # Send a different body with the original signature.
    tampered = b'{"event":"meeting.started","payload":{"foo":"EVIL"}}'
    status, _ = _post(
        port,
        tampered,
        headers={"X-Zm-Request-Timestamp": timestamp, "X-Zm-Signature": sig},
    )

    assert status == 401
    assert captured == []
