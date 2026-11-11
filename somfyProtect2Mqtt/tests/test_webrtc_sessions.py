"""ICE parsing and isolation of successive camera sessions."""

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
        # hls_segments is kept after reset so in-flight HTTP requests can still
        # read existing segments; it is only superseded by the next _init_hls_muxer.
        assert "camera" in handler.hls_segments
        assert handler.hls_segments["camera"]["playlist"] == b"old playlist"
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


def test_overlapping_offers_preserve_latest_session(monkeypatch):

    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        closing = asyncio.Event()
        finish_close = asyncio.Event()

        async def slow_close():
            closing.set()
            await finish_close.wait()

        handler.peer_connections["old"] = SimpleNamespace(close=slow_close)
        handler.device_sessions["camera"] = "old"

        class Peer:
            async def close(self):
                pass

            async def setRemoteDescription(self, description):
                handler._init_hls_muxer("camera")

            async def createAnswer(self):
                return SimpleNamespace(sdp="v=0", type="answer")

            async def setLocalDescription(self, description):
                pass

        monkeypatch.setattr("somfy_protect.webrtc_handler.RTCPeerConnection", lambda **kwargs: Peer())
        monkeypatch.setattr(handler, "_setup_event_handlers", lambda *args: None)
        monkeypatch.setattr(handler, "_wait_for_ice_gathering", AsyncMock())
        monkeypatch.setattr(handler, "_send_answer_and_candidates", AsyncMock())

        def offer(session):
            return {
                "device_id": "camera",
                "site_id": "home",
                "session_id": session,
                "offer": {"sdp": "v=0", "type": "offer"},
            }

        earlier = asyncio.create_task(handler.handle_offer(offer("earlier")))
        await asyncio.wait_for(closing.wait(), 1)
        later = asyncio.create_task(handler.handle_offer(offer("later")))
        await asyncio.sleep(0)
        finish_close.set()
        await asyncio.wait_for(asyncio.gather(earlier, later), 2)
        try:
            assert handler.device_sessions["camera"] == "later"
            assert set(handler.peer_connections) == {"later"}
            assert Path(handler.hls_muxers["camera"]["temp_dir"]).exists()
        finally:
            await handler.cleanup()

    asyncio.run(scenario())


@pytest.mark.parametrize("event", ["hangup", "candidate", "cleanup"])
def test_pending_offer_handles_session_events(monkeypatch, event):
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        negotiating = asyncio.Event()
        resume = asyncio.Event()
        peers = []

        class Peer:
            def __init__(self, **kwargs):
                self.candidates = []
                peers.append(self)

            async def close(self):
                pass

            async def setRemoteDescription(self, description):
                pass

            async def createAnswer(self):
                return SimpleNamespace(sdp="v=0", type="answer")

            async def setLocalDescription(self, description):
                if self is peers[0]:
                    negotiating.set()
                    await resume.wait()

            async def addIceCandidate(self, candidate):
                self.candidates.append(candidate)

        monkeypatch.setattr("somfy_protect.webrtc_handler.RTCPeerConnection", Peer)
        monkeypatch.setattr(handler, "_setup_event_handlers", lambda *args: None)
        monkeypatch.setattr(handler, "_wait_for_ice_gathering", AsyncMock())
        monkeypatch.setattr(handler, "_send_answer_and_candidates", AsyncMock())

        def offer(session):
            return {
                "device_id": "camera",
                "site_id": "home",
                "session_id": session,
                "offer": {"sdp": "v=0", "type": "offer"},
            }

        first = asyncio.create_task(handler.handle_offer(offer("first")))
        await asyncio.wait_for(negotiating.wait(), 1)
        second = asyncio.create_task(handler.handle_offer(offer("second")))
        await asyncio.sleep(0)
        if event == "hangup":
            await handler.close_session("second")
        elif event == "cleanup":
            await handler.cleanup()
        else:
            await handler.add_remote_candidate("second", None)
        resume.set()
        await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 2)
        try:
            if event == "hangup":
                assert set(handler.peer_connections) == {"first"}
            elif event == "cleanup":
                assert not handler.peer_connections
            else:
                assert peers[1].candidates == [None]
        finally:
            await handler.cleanup()

    asyncio.run(scenario())


@pytest.mark.parametrize("video_ready", [False, True])
def test_audio_timeout_is_reported_only_after_video_starts(video_ready, caplog):
    from aiortc.mediastreams import MediaStreamError

    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler._init_hls_muxer("camera")
        muxer = handler.hls_muxers["camera"]
        for task in muxer["tasks"]:
            task.cancel()
        await asyncio.gather(*muxer["tasks"], return_exceptions=True)
        muxer["video_ready"] = video_ready
        track = SimpleNamespace(recv=AsyncMock(side_effect=[asyncio.TimeoutError, MediaStreamError]))
        try:
            await handler._read_audio_frames("camera", track)
        finally:
            await handler.cleanup()

    asyncio.run(scenario())
    assert ("No audio frames from camera" in caplog.text) == video_ready


def test_hls_segments_remain_accessible_after_session_reset():
    """HLS playlist must stay readable until a new session replaces it."""

    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler._init_hls_muxer("camera")
        # Simulate a segment being written so the playlist is non-empty
        handler.hls_segments["camera"]["playlist"] = b"#EXTM3U\n"
        handler.hls_segments["camera"]["segment0.ts"] = b"\x47" * 188
        # A hang_up triggers _reset_hls_muxer; segments must still be reachable
        await handler._reset_hls_muxer("camera")
        assert "camera" in handler.hls_segments, "segments must survive reset"
        assert handler.hls_segments["camera"].get("playlist"), "playlist must survive reset"
        assert handler.hls_segments["camera"].get("segment0.ts"), "segment must survive reset"
        await handler.cleanup()

    asyncio.run(scenario())
