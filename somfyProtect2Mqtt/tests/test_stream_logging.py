"""Stream credentials and signed URLs must not appear in normal logs."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from somfy_protect.webrtc_handler import WebRTCHandler
from somfy_protect.websocket import SomfyProtectWebsocket


@pytest.mark.parametrize("key", ["snapshotready", "video.webrtc.answer", "video.webrtc.turn.config"])
def test_incoming_stream_events_do_not_log_secrets(key, monkeypatch, caplog):
    client = SomfyProtectWebsocket.__new__(SomfyProtectWebsocket)
    client.mqtt_config = {}
    client.mqtt_client = None
    client.webrtc_handler = WebRTCHandler(None, {}, lambda message: None)
    published = []
    monkeypatch.setattr("somfy_protect.websocket.mqtt_publish", lambda **kwargs: published.append(kwargs))
    message = {
        "key": key,
        "session_id": "session",
        "snapshot_url": "https://example.invalid/image?Signature=private-secret",
        "answer": "a=ice-pwd:private-secret",
        "turn": {"url": "turn:example.invalid", "password": "private-secret"},
    }
    with caplog.at_level(logging.INFO):
        client._default_message(message)
        if key == "video.webrtc.answer":
            client._video_webrtc_answer(message)
        elif key == "video.webrtc.turn.config":
            client._video_webrtc_turn_config(message)
    assert "private-secret" not in caplog.text
    if key == "snapshotready":
        assert published[0]["payload"] == message
    else:
        assert not published


def test_outgoing_answer_preserves_sdp_without_logging_credentials(caplog):
    messages = []
    handler = WebRTCHandler(None, {}, messages.append)
    pc = SimpleNamespace(localDescription=SimpleNamespace(sdp="v=0\r\na=ice-pwd:private-secret\r\n", type="answer"))
    with caplog.at_level(logging.INFO):
        asyncio.run(handler._send_answer_and_candidates(pc, "session"))
    assert "private-secret" not in caplog.text
    assert "private-secret" in str(messages)


def test_disconnected_socket_does_not_log_outgoing_credentials(caplog):
    client = SomfyProtectWebsocket.__new__(SomfyProtectWebsocket)
    client._websocket = None
    with caplog.at_level(logging.INFO):
        client.send_websocket_message({"key": "video.webrtc.answer", "answer": "private-secret"})
    assert "private-secret" not in caplog.text
    assert "not connected" in caplog.text


def test_rejected_offer_does_not_log_sdp_credentials(caplog):
    handler = WebRTCHandler(None, {}, lambda message: None)
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        asyncio.run(handler._handle_offer({"offer": {"sdp": "a=ice-pwd:private-secret", "type": "offer"}}))
    assert "private-secret" not in caplog.text
