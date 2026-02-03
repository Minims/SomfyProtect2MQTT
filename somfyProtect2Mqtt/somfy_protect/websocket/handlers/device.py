"""Device event handlers for Somfy Protect WebSocket.

This module contains handlers for device-related events:
- device_status: Device status update (motion detected)
- device_ring_door_bell: Doorbell ringing
- device_missed_call: Missed doorbell call
- device_doorlock_triggered: Door lock state change
- update_keyfob_presence: Key fob presence (home/away)
- device_gate_triggered_*: Gate control events
- device_answered_call_*: Call answered events
"""

import logging
import time

from business import update_visiophone_snapshot, write_to_media_folder
from business.mqtt import mqtt_publish, update_device

LOGGER = logging.getLogger(__name__)


def handle_device_status(ws, message: dict) -> None:
    """Handle device status update (motion detected).
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id and device_id
    """
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    LOGGER.info(f"It seems the device {device_id} is moving")
    
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/pir"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"motion_sensor": "True"}, retain=True)
    time.sleep(3)
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"motion_sensor": "False"}, retain=True)


def handle_device_ring_door_bell(ws, message: dict) -> None:
    """Handle doorbell ringing event.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id, device_id, and optional snapshot_url
    """
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    LOGGER.info(f"Someone is ringing on {device_id}")
    
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/ringing"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"ringing": "True"}, retain=True)
    time.sleep(3)
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"ringing": "False"}, retain=True)
    
    snapshot_url = message.get("snapshot_url")
    if snapshot_url:
        LOGGER.info("Found a snapshot!")
        update_visiophone_snapshot(
            url=snapshot_url,
            site_id=site_id,
            device_id=device_id,
            mqtt_client=ws.mqtt_client,
            mqtt_config=ws.mqtt_config,
        )


def handle_device_missed_call(ws, message: dict) -> None:
    """Handle missed doorbell call.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing snapshot and clip URLs
    """
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    LOGGER.info(f"Someone has rang on {device_id}")
    
    snapshot_cloudfront_url = message.get("snapshot_cloudfront_url")
    clip_cloudfront_url = message.get("clip_cloudfront_url")
    
    if snapshot_cloudfront_url:
        LOGGER.info("Found a snapshot!")
        update_visiophone_snapshot(
            url=snapshot_cloudfront_url,
            site_id=site_id,
            device_id=device_id,
            mqtt_client=ws.mqtt_client,
            mqtt_config=ws.mqtt_config,
        )
    
    if clip_cloudfront_url:
        LOGGER.info("Found Clip!")
        write_to_media_folder(
            url=clip_cloudfront_url,
            site_id=site_id,
            device_id=device_id,
            label="videophone",
            event_id=message.get("event_id", "unknown"),
            occurred_at=message.get("occurred_at", "unknown"),
            media_type="video",
            mqtt_client=ws.mqtt_client,
            mqtt_config=ws.mqtt_config,
        )


def handle_device_doorlock_triggered(ws, message: dict) -> None:
    """Handle door lock state change.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing door lock status
    """
    LOGGER.info("Update Door Lock Triggered")
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    LOGGER.info(message)
    
    door_lock_status = message.get("door_lock_status", "unknown")
    if door_lock_status and door_lock_status != "unknown":
        payload = {"open_door": door_lock_status}
        topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/state"
        mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)
    
    update_device(ws.api, ws.mqtt_client, ws.mqtt_config, site_id, device_id)


def handle_keyfob_presence(ws, message: dict) -> None:
    """Handle key fob presence update (home/away).
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing presence_in or presence_out key
    """
    LOGGER.info("Update Key Fob Presence")
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    LOGGER.info(message)
    
    payload = {"presence": "unknown"}
    if message.get("key") == "presence_out":
        payload = {"presence": "not_home"}
    if message.get("key") == "presence_in":
        payload = {"presence": "home"}
    
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/presence"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)


def handle_device_gate_triggered_from_monitor(ws, message: dict) -> None:
    """Handle gate opened from monitor."""
    LOGGER.info(f"Gate Open from Monitor: {message}")


def handle_device_gate_triggered_from_mobile(ws, message: dict) -> None:
    """Handle gate opened from mobile app."""
    LOGGER.info(f"Gate Open from Mobile: {message}")


def handle_device_answered_call_from_monitor(ws, message: dict) -> None:
    """Handle call answered from monitor."""
    LOGGER.info(f"Answer Call from Monitor: {message}")


def handle_device_answered_call_from_mobile(ws, message: dict) -> None:
    """Handle call answered from mobile app."""
    LOGGER.info(f"Answer Call from Mobile: {message}")
