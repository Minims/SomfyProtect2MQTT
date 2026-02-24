"""Video websocket handlers."""

# pylint: disable=protected-access,duplicate-code

import logging
import os

from business.mqtt import mqtt_publish
from business.streaming.camera import VideoCamera

LOGGER = logging.getLogger(__name__)


def video_stream_ready(websocket_client, message: dict) -> None:
    """Handle video stream ready events."""
    LOGGER.info("Stream URL Found")
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    stream_url = str(message.get("stream_url") or "")
    topic = f"{websocket_client.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/stream"
    mqtt_publish(
        mqtt_client=websocket_client.mqtt_client,
        topic=topic,
        payload=stream_url,
        retain=False,
    )

    if websocket_client.streaming_config == "go2rtc":
        directory = "/config/somfyprotect2mqtt"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(f"{directory}/stream_url_{device_id}", "w", encoding="utf-8") as file:
                file.write(stream_url)
        except OSError as e:
            LOGGER.warning(f"Unable to create directory {directory}: {e}")

    if websocket_client.streaming_config == "mqtt":
        websocket_client._run_io_task(stream_video_to_mqtt, websocket_client, site_id, device_id, stream_url)


def stream_video_to_mqtt(websocket_client, site_id: str, device_id: str, stream_url: str) -> None:
    """Stream camera frames and publish snapshots to MQTT."""
    camera = VideoCamera(url=stream_url)
    frame = None
    try:
        while camera.is_opened():
            frame = camera.get_frame()
            if frame is None:
                break
            websocket_client._publish_snapshot_bytes(site_id, device_id, bytearray(frame))
    finally:
        camera.release()
