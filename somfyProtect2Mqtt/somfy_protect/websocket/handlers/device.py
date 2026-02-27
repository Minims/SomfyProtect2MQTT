"""Device websocket handlers."""

# pylint: disable=protected-access

import logging

from business import update_visiophone_snapshot, write_to_media_folder
from business.mqtt import mqtt_publish, update_device

LOGGER = logging.getLogger(__name__)


def pulse_motion_sensor(websocket_client, site_id: str, device_id: str) -> None:
    """Publish a motion pulse for PIR topics."""
    topic = f"{websocket_client.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/pir"
    mqtt_publish(
        mqtt_client=websocket_client.mqtt_client,
        topic=topic,
        payload={"motion_sensor": "True"},
        retain=True,
    )
    websocket_client._run_io_task(websocket_client._publish_false_after_delay, topic, "motion_sensor")


def device_ring_door_bell(websocket_client, message: dict) -> None:
    """Handle door bell ring events."""
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    if not site_id or not device_id:
        LOGGER.warning("Missing site_id or device_id for ring event")
        return

    mqtt_config = websocket_client.mqtt_config or {}
    topic_prefix = mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    topic = f"{topic_prefix}/{site_id}/{device_id}/ringing"
    mqtt_publish(
        mqtt_client=websocket_client.mqtt_client,
        topic=topic,
        payload={"ringing": "True"},
        retain=True,
    )
    websocket_client._run_io_task(websocket_client._publish_false_after_delay, topic, "ringing")

    snapshot_url = message.get("snapshot_url")
    if snapshot_url:
        websocket_client._run_io_task(
            update_visiophone_snapshot,
            url=snapshot_url,
            site_id=site_id,
            device_id=device_id,
            mqtt_client=websocket_client.mqtt_client,
            mqtt_config=mqtt_config,
        )


def device_missed_call(websocket_client, message: dict) -> None:
    """Handle missed call events."""
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    if not site_id or not device_id:
        LOGGER.warning("Missing site_id or device_id for missed call")
        return

    mqtt_config = websocket_client.mqtt_config or {}
    snapshot_url = message.get("snapshot_cloudfront_url")
    clip_url = message.get("clip_cloudfront_url")

    if snapshot_url:
        websocket_client._run_io_task(
            update_visiophone_snapshot,
            url=snapshot_url,
            site_id=site_id,
            device_id=device_id,
            mqtt_client=websocket_client.mqtt_client,
            mqtt_config=mqtt_config,
        )

    if clip_url:
        websocket_client._run_io_task(
            write_to_media_folder,
            url=clip_url,
            site_id=site_id,
            device_id=device_id,
            label=message.get("label") or device_id,
            event_id=message.get("event_id") or "unknown",
            occurred_at=message.get("occurred_at") or "unknown",
            media_type="video",
            mqtt_client=websocket_client.mqtt_client,
            mqtt_config=mqtt_config,
        )


def device_doorlock_triggered(websocket_client, message: dict) -> None:
    """Handle door lock triggered events."""
    LOGGER.info("Update Door Lock Triggered")
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    if not site_id or not device_id:
        LOGGER.warning("Missing site_id or device_id for door lock event")
        return
    door_lock_status = message.get("door_lock_status", "unknown")
    if door_lock_status and door_lock_status != "unknown":
        topic = f"{websocket_client.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/state"
        mqtt_publish(
            mqtt_client=websocket_client.mqtt_client,
            topic=topic,
            payload={"open_door": door_lock_status},
            retain=True,
        )
    update_device(websocket_client.api, websocket_client.mqtt_client, websocket_client.mqtt_config, site_id, device_id)


def update_keyfob_presence(websocket_client, message: dict) -> None:
    """Handle keyfob presence events."""
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    if not site_id or not device_id:
        LOGGER.warning("Missing site_id or device_id for keyfob presence event")
        return
    payload = {"presence": "unknown"}
    if message.get("key") == "presence_out":
        payload = {"presence": "not_home"}
    if message.get("key") == "presence_in":
        payload = {"presence": "home"}

    topic = f"{websocket_client.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/presence"
    mqtt_publish(
        mqtt_client=websocket_client.mqtt_client,
        topic=topic,
        payload=payload,
        retain=True,
    )


def device_status(websocket_client, message: dict) -> None:
    """Handle device status movement events."""
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    if not site_id or not device_id:
        LOGGER.warning("Missing site_id or device_id for device status event")
        return
    pulse_motion_sensor(websocket_client, site_id, device_id)
