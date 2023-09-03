"""Streaming Module"""
import logging

import ffmpeg_streaming
from ffmpeg_streaming import Bitrate, Formats, Representation, Size

LOGGER = logging.getLogger(__name__)


def rtmps_to_hls(device_id: str, url: str, path: str):
    LOGGER.info(f"Path: {path}")
    _1080p = Representation(Size(1920, 1080), Bitrate(4096 * 1024, 640 * 1024))
    video = ffmpeg_streaming.input(url)
    hls = video.hls(Formats.h264())
    hls.representations(_1080p)
    hls.output(f"{path}/{device_id}.m3u8")
