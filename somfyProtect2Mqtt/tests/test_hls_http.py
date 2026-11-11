"""Check the HTTP responses consumed by HLS players."""

import asyncio
from urllib.request import urlopen

from somfy_protect.webrtc_handler import WebRTCHandler


def test_hls_responses_advertise_the_complete_body_length():
    handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc", "127.0.0.1", 0)
    handler.hls_segments["camera"] = {}
    handler._start_hls_server("camera")
    port = handler.hls_server.server_port
    try:
        for filename, body in (
            ("playlist.m3u8", b""),
            ("playlist.m3u8", b"#EXTM3U\n#EXTINF:1,\nsegment0.ts\n"),
            ("segment0.ts", b"\x47" + bytes(187)),
        ):
            key = "playlist" if filename.endswith(".m3u8") else filename
            handler.hls_segments["camera"][key] = body
            with urlopen(f"http://127.0.0.1:{port}/camera/{filename}", timeout=2) as response:
                assert response.status == 200
                assert response.headers.get("Content-Length") == str(len(body))
                assert response.read() == body
    finally:
        asyncio.run(handler.cleanup())
