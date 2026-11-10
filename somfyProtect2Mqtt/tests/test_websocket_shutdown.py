"""Shutdown must leave no pending work on the WebSocket event loop."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiortc import RTCConfiguration, RTCPeerConnection, VideoStreamTrack
from somfy_protect.websocket import SomfyProtectWebsocket


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("somfy_protect.websocket.WebSocketApp", Mock())
    sso = SimpleNamespace(get_token=lambda: {"access_token": "test"})
    instance = SomfyProtectWebsocket(sso, {"mqtt": {}}, None, None)
    started = threading.Event()
    instance.loop.call_soon_threadsafe(started.set)
    assert started.wait(1)
    yield instance
    instance.close()


def test_concurrent_close_runs_cleanup_once(client, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()
    calls = []

    async def cleanup():
        calls.append(1)
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        cleaned.set()

    monkeypatch.setattr(client.webrtc_handler, "cleanup", cleanup)
    first = threading.Thread(target=client.close)
    second = threading.Thread(target=client.close)
    first.start()
    try:
        assert entered.wait(1)
        second.start()
        # A repeat call must not wait on the thread whose exit triggered it.
        second.join(timeout=0.5)
        assert not second.is_alive()
    finally:
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)
    assert calls == [1]
    assert cleaned.is_set()
    assert client.loop.is_closed()
    assert not client.loop_thread.is_alive()


def test_close_awaits_pending_task_finalizers(client):
    cancelled = threading.Event()

    async def pending():
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cancelled.set()

    async def start():
        task = asyncio.create_task(pending())
        await asyncio.sleep(0)
        return task

    task = asyncio.run_coroutine_threadsafe(start(), client.loop).result(timeout=1)
    client.close()
    assert cancelled.is_set()
    assert task.done()
    assert client.loop.is_closed()


def test_messages_after_close_do_not_create_coroutines(client, monkeypatch):
    client.close()
    callback = AsyncMock()
    monkeypatch.setattr(client, "on_message", callback)
    client._on_message_wrapper(None, '{"key": "ignored"}')
    callback.assert_not_called()


def test_cleanup_timeout_still_drains_the_loop(client, monkeypatch, caplog):
    cancelled = threading.Event()

    async def cleanup():
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cancelled.set()

    monkeypatch.setattr(client.webrtc_handler, "cleanup", cleanup)
    client.close()
    assert "cleanup timed out" in caplog.text
    assert cancelled.is_set()
    assert client.loop.is_closed()
    assert not asyncio.all_tasks(client.loop)


def test_close_connected_peers_after_receiving_video(client):
    async def connect():
        sender = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        receiver = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        client.webrtc_handler.peer_connections.update(sender=sender, receiver=receiver)
        sender.addTrack(VideoStreamTrack())
        received = asyncio.get_running_loop().create_future()

        @receiver.on("track")
        def on_track(track):
            received.set_result(track)

        await sender.setLocalDescription(await sender.createOffer())
        await receiver.setRemoteDescription(sender.localDescription)
        await receiver.setLocalDescription(await receiver.createAnswer())
        await sender.setRemoteDescription(receiver.localDescription)
        track = await received
        frame = await asyncio.wait_for(track.recv(), timeout=5)
        assert frame.width > 0
        return sender, receiver

    peers = asyncio.run_coroutine_threadsafe(connect(), client.loop).result(timeout=10)
    client.close()
    assert all(peer.connectionState == "closed" for peer in peers)
    assert not asyncio.all_tasks(client.loop)
    assert client.loop.is_closed()
