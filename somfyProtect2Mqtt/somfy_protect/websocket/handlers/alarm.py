"""Alarm websocket handlers."""

# pylint: disable=protected-access

import logging

from business.alarm_state import ALARM_STATE_LOCK, end_alarm, invalidate_site_refresh, start_alarm
from business.mqtt import mqtt_publish, publish_site_state, update_site
from somfy_protect.websocket.handlers.device import pulse_motion_sensor

LOGGER = logging.getLogger(__name__)


def security_level_change(websocket_client, message: dict) -> None:
    """Update alarm status."""
    LOGGER.info("Update Alarm Status")
    site_id = message.get("site_id")
    if not site_id:
        LOGGER.warning("Missing site_id for security level change")
        return
    security_level = message.get("security_level")
    with ALARM_STATE_LOCK:
        invalidate_site_refresh(site_id)
        publish_site_state(websocket_client.mqtt_client, websocket_client.mqtt_config, site_id, str(security_level))


def alarm_trespass(websocket_client, message: dict) -> None:
    """Handle trespass alarm events."""
    LOGGER.info("Report Alarm Triggered")
    site_id = message.get("site_id")
    if not site_id:
        LOGGER.warning("Missing site_id for alarm trespass event")
        return
    device_id = message.get("device_id")
    device_type = message.get("device_type")
    if message.get("type") != "alarm":
        LOGGER.info(f"{message.get('type')} is not 'alarm'")

    topic_prefix = websocket_client.mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    with ALARM_STATE_LOCK:
        start_alarm(site_id, message.get("end_at"))
        mqtt_publish(
            mqtt_client=websocket_client.mqtt_client,
            topic=f"{topic_prefix}/{site_id}/state",
            payload={"security_level": "triggered"},
            retain=True,
        )

    if device_type == "pir" and device_id:
        pulse_motion_sensor(websocket_client, site_id, device_id)


def alarm_panic(websocket_client, message: dict) -> None:
    """Handle panic alarm events."""
    LOGGER.info("Report Alarm Panic")
    site_id = message.get("site_id")
    if not site_id:
        LOGGER.warning("Missing site_id for alarm panic event")
        return
    topic = f"{websocket_client.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"
    with ALARM_STATE_LOCK:
        start_alarm(site_id, message.get("end_at"))
        mqtt_publish(
            mqtt_client=websocket_client.mqtt_client,
            topic=topic,
            payload={"security_level": "triggered"},
            retain=True,
        )


def alarm_domestic_fire(websocket_client, message: dict) -> None:
    """Handle domestic fire alarm start events."""
    LOGGER.info("Report Alarm Fire")
    site_id = message.get("site_id")
    topic_prefix = websocket_client.mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    for device_id in message.get("devices", []):
        topic = f"{topic_prefix}/{site_id}/{device_id}/fire"
        mqtt_publish(
            mqtt_client=websocket_client.mqtt_client,
            topic=topic,
            payload={"smoke": "True"},
            retain=True,
        )


def alarm_domestic_fire_end(websocket_client, message: dict) -> None:
    """Handle domestic fire alarm end events."""
    LOGGER.info("Report Alarm Fire")
    site_id = message.get("site_id")
    topic_prefix = websocket_client.mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    for device_id in message.get("devices", []):
        topic = f"{topic_prefix}/{site_id}/{device_id}/fire"
        mqtt_publish(
            mqtt_client=websocket_client.mqtt_client,
            topic=topic,
            payload={"smoke": "False"},
            retain=True,
        )


def alarm_end(websocket_client, message: dict) -> None:
    """Handle alarm end events."""
    LOGGER.info("Report Alarm Stop")
    site_id = message.get("site_id")
    if site_id:
        end_alarm(site_id)
    update_site(websocket_client.api, websocket_client.mqtt_client, websocket_client.mqtt_config, site_id)
