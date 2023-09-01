"""Streaming Module"""
import ffmpeg_streaming
from ffmpeg_streaming import Formats, Bitrate, Representation, Size
import logging


LOGGER = logging.getLogger(__name__)


def hls(device_id: str, url: str):
    _720p = Representation(Size(1280, 720), Bitrate(2048 * 1024, 320 * 1024))
    video = ffmpeg_streaming.input(url)
    LOGGER.info(f"video: {video}")
    hls = video.hls(Formats.h264())
    LOGGER.info(f"hls: {hls}")
    repr = hls.representations(_720p)
    LOGGER.info(f"repr: {repr}")
    hls.output(f"{device_id}.m3u8")
