"""Exercise the native codecs used by the camera bridge."""

import asyncio
from fractions import Fraction
from io import BytesIO

import av
from PIL import Image
from somfy_protect.webrtc_handler import SilenceAudioTrack, WebRTCHandler


def test_hls_segment_encodes_and_decodes_video_and_audio():
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler._init_hls_muxer("camera")
        muxer = handler.hls_muxers["camera"]
        # Drive segment creation directly, without wall-clock segmentation.
        for task in muxer["tasks"]:
            task.cancel()
        await asyncio.gather(*muxer["tasks"], return_exceptions=True)
        track = SilenceAudioTrack()
        try:
            video = av.VideoFrame.from_image(Image.new("RGB", (320, 240), "red"))
            audio = await track.recv()
            muxer["video_ready"] = muxer["audio_ready"] = True
            muxer["video_queue"].put_nowait(video)
            muxer["audio_queue"].put_nowait(audio)
            await handler._create_hls_segment("camera")
            assert muxer["video_stream"] is not None
            assert muxer["audio_stream"] is not None
            for index in range(30):
                video.pts = index * 3000
                video.time_base = Fraction(1, 90000)
                for packet in muxer["video_stream"].encode(video):
                    muxer["container"].mux(packet)
                audio.pts = index * audio.samples
                for packet in muxer["audio_stream"].encode(audio):
                    muxer["container"].mux(packet)
            await handler._close_hls_segment("camera")
            segments = handler.hls_segments["camera"]
            assert b"segment0.ts" in segments["playlist"]
            with av.open(BytesIO(segments["segment0.ts"])) as container:
                frames = list(container.decode(video=0))
                assert len(frames) == 30
                assert {(frame.width, frame.height) for frame in frames} == {(320, 240)}
            with av.open(BytesIO(segments["segment0.ts"])) as container:
                frames = list(container.decode(audio=0))
                assert frames
                assert all(frame.sample_rate == 48000 for frame in frames)
        finally:
            track.stop()
            await handler.cleanup()

    asyncio.run(scenario())
