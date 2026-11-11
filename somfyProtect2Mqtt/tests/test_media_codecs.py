"""Exercise the native codecs used by the camera bridge."""

import asyncio
from fractions import Fraction
from io import BytesIO

import av
from aiortc import VideoStreamTrack
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


def test_live_hls_video_timestamps_match_playlist_durations():
    _check_live_hls_timestamps(with_audio=False)


def test_live_hls_audio_and_video_stay_synchronized():
    _check_live_hls_timestamps(with_audio=True)


def _check_live_hls_timestamps(with_audio):
    async def scenario():
        handler = WebRTCHandler(None, {}, lambda message: None, "go2rtc")
        handler._init_hls_muxer("camera")
        muxer = handler.hls_muxers["camera"]
        tracks = [VideoStreamTrack()]
        readers = [handler._read_video_frames]
        if with_audio:
            tracks.append(SilenceAudioTrack())
            readers.append(handler._read_audio_frames)
        for reader, track in zip(readers, tracks):
            task = asyncio.create_task(reader("camera", track))
            muxer["tasks"].add(task)
            handler.active_tasks.add(task)
            task.add_done_callback(handler.active_tasks.discard)
        try:
            async with asyncio.timeout(10):
                while "segment1.ts" not in handler.hls_segments["camera"]:
                    await asyncio.sleep(0.05)
            previous_video_end = None
            for filename in ("segment0.ts", "segment1.ts"):
                payload = handler.hls_segments["camera"][filename]
                with av.open(BytesIO(payload)) as container:
                    video_times = [frame.time for frame in container.decode(video=0)]
                assert len(video_times) >= 10
                duration = muxer["segment_durations"][filename]
                assert 0.5 * duration < video_times[-1] - video_times[0] < 1.5 * duration
                assert all(0 <= later - earlier < 0.2 for earlier, later in zip(video_times, video_times[1:]))
                if previous_video_end is not None:
                    assert 0 <= video_times[0] - previous_video_end < 0.2
                previous_video_end = video_times[-1]
                if with_audio:
                    with av.open(BytesIO(payload)) as container:
                        audio_times = [frame.time for frame in container.decode(audio=0)]
                    assert len(audio_times) >= 10
                    assert abs(audio_times[-1] - video_times[-1]) < 0.5
        finally:
            for track in tracks:
                track.stop()
            await handler.cleanup()

    asyncio.run(scenario())
