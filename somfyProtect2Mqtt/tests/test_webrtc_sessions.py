"""ICE parsing and isolation of successive camera sessions."""

import asyncio
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest
from somfy_protect.webrtc_handler import WebRTCHandler

with patch.dict(sys.modules, {"cv2": ModuleType("cv2")}):
    from somfy_protect.websocket import SomfyProtectWebsocket


def test_candidate_parsing_and_end_marker():
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None)
        pc = AsyncMock()
        handler.peer_connections["s"] = pc
        await handler.add_remote_candidate(
            "s", {"sdp": "candidate:1 1 udp 123 192.0.2.1 4567 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
        )
        candidate = pc.addIceCandidate.call_args.args[0]
        assert (candidate.foundation, candidate.ip, candidate.port, candidate.sdpMid) == ("1", "192.0.2.1", 4567, "0")
        await handler.add_remote_candidate("s", None)
        pc.addIceCandidate.assert_awaited_with(None)

    asyncio.run(scenario())


def test_hangup_releases_muxer_and_playlist():
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler.peer_connections["s"] = AsyncMock()
        handler.device_sessions["camera"] = "s"
        handler._init_hls_muxer("camera")
        old = handler.hls_muxers["camera"]
        handler.hls_segments["camera"]["playlist"] = b"old playlist"
        await handler.close_session("s")
        assert "camera" not in handler.hls_segments
        assert not Path(old["temp_dir"]).exists()
        assert all(task.done() for task in old["tasks"])
        handler._init_hls_muxer("camera")
        assert not handler.hls_muxers["camera"]["stopped"]
        assert handler.hls_segments["camera"]["playlist"] == b""
        await handler.cleanup()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "request_id,owned,accepted", [(None, False, True), ("app", False, False), ("ours", True, True)]
)
def test_offers_from_other_clients_are_ignored(request_id, owned, accepted):
    async def scenario():
        client = SomfyProtectWebsocket.__new__(SomfyProtectWebsocket)
        client._owned_webrtc_sessions = set()
        client._requested_webrtc_sessions = {request_id} if owned else set()
        client.webrtc_handler = AsyncMock()
        client._video_webrtc_session({"session_id": "s", "request_session_id": request_id})
        await client._video_webrtc_offer({"session_id": "s"})
        assert client.webrtc_handler.handle_offer.await_count == int(accepted)

    asyncio.run(scenario())


def test_late_hangup_does_not_remove_replacement_stream():
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler.peer_connections["old"] = AsyncMock()
        handler.peer_connections["new"] = AsyncMock()
        handler.device_sessions["camera"] = "new"
        handler._init_hls_muxer("camera")
        handler.hls_segments["camera"]["playlist"] = b"new playlist"
        await handler.close_session("old")
        assert handler.hls_segments["camera"]["playlist"] == b"new playlist"
        assert handler.device_sessions["camera"] == "new"
        await handler.cleanup()

    asyncio.run(scenario())


@pytest.mark.parametrize("candidate", [{}, [], {"sdp": 42}, {"sdp": "invalid"}])
def test_malformed_candidate_does_not_end_gathering(candidate):
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None)
        pc = AsyncMock()
        handler.peer_connections["s"] = pc
        await handler.add_remote_candidate("s", candidate)
        pc.addIceCandidate.assert_not_awaited()

    asyncio.run(scenario())


def test_offer_without_session_announcement_is_ignored():
    async def scenario():
        client = SomfyProtectWebsocket.__new__(SomfyProtectWebsocket)
        client._owned_webrtc_sessions = set()
        client.webrtc_handler = AsyncMock()
        await client._video_webrtc_offer({"session_id": "unannounced"})
        client.webrtc_handler.handle_offer.assert_not_awaited()

    asyncio.run(scenario())
