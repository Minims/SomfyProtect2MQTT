"""Video event handlers for Somfy Protect WebSocket.

This module contains handlers for video/streaming-related events:
- video_stream_ready: RTMP stream URL available
- video_webrtc_*: WebRTC signaling events
"""

import logging
import os

from business.mqtt import mqtt_publish
from business.streaming.camera import VideoCamera

LOGGER = logging.getLogger(__name__)


def handle_video_stream_ready(ws, message: dict) -> None:
    """Handle video stream ready event.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing stream_url
    """
    LOGGER.info("Stream URL Found")
    LOGGER.info(message)
    
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    stream_url = message.get("stream_url")
    
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/stream"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=stream_url, retain=False)

    # Handle go2rtc streaming config
    if ws.streaming_config == "go2rtc":
        directory = "/config/somfyprotect2mqtt"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(f"{directory}/stream_url_{device_id}", "w", encoding="utf-8") as file:
                file.write(stream_url)
        except OSError as exc:
            LOGGER.warning(f"Unable to create directory {directory}: {exc}")

    # Handle MQTT streaming config
    if ws.streaming_config == "mqtt":
        LOGGER.info("Start MQTT Image")
        camera = VideoCamera(url=stream_url)
        while camera.is_opened():
            frame = camera.get_frame()
            if frame is None:
                break
            byte_arr = bytearray(frame)
            topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
            mqtt_publish(
                mqtt_client=ws.mqtt_client,
                topic=topic,
                payload=byte_arr,
                retain=True,
                is_json=False,
                qos=2,
            )
        camera.release()


async def handle_video_webrtc_offer(ws, message: dict) -> None:
    """Handle WebRTC offer from camera."""
    await ws.webrtc_handler.handle_offer(message)


async def handle_video_webrtc_candidate(ws, message: dict) -> None:
    """Handle WebRTC ICE candidate from camera."""
    session_id = message.get("session_id")
    candidate_data = message.get("candidate")
    await ws.webrtc_handler.add_remote_candidate(session_id, candidate_data)


async def handle_video_webrtc_hang_up(ws, message: dict) -> None:
    """Handle WebRTC session hang up."""
    LOGGER.info(f"WEBRTC HangUp: {message}")
    session_id = message.get("session_id")
    await ws.webrtc_handler.close_session(session_id)


def handle_video_webrtc_keep_alive(ws, message: dict) -> None:
    """Handle WebRTC keep alive."""
    LOGGER.info(f"WEBRTC KeepAlive: {message}")


def handle_video_webrtc_session(ws, message: dict) -> None:
    """Handle WebRTC session creation."""
    LOGGER.info(f"WEBRTC Session: {message}")


def handle_video_webrtc_start(ws, message: dict) -> None:
    """Handle WebRTC start."""
    LOGGER.info(f"WEBRTC Start: {message}")


def handle_video_webrtc_answer(ws, message: dict) -> None:
    """Handle WebRTC answer."""
    LOGGER.info(f"WEBRTC Answer: {message}")


def handle_video_webrtc_turn_config(ws, message: dict) -> None:
    """Handle WebRTC TURN server configuration."""
    LOGGER.info(f"WEBRTC Turn Config: {message}")
    session_id = message.get("session_id")
    turn_data = message.get("turn")
    ws.webrtc_handler.store_turn_config(session_id, turn_data)
