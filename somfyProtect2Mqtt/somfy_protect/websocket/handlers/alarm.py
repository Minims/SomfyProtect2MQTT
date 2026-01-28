"""Alarm event handlers for Somfy Protect WebSocket.

This module contains handlers for alarm-related events:
- security_level_change: Alarm status changes (armed, disarmed, partial)
- alarm_trespass: Intrusion detected
- alarm_panic: Panic button triggered
- alarm_domestic_fire: Fire/smoke detected
- alarm_domestic_fire_end: Fire/smoke cleared
- alarm_end: Alarm stopped
"""

import logging
import time

from business.mqtt import mqtt_publish, update_site
from homeassistant.ha_discovery import ALARM_STATUS

LOGGER = logging.getLogger(__name__)


def handle_security_level_change(ws, message: dict) -> None:
    """Handle alarm security level change.
    
    Args:
        ws: WebSocket instance with mqtt_client, mqtt_config, api
        message: WebSocket message containing site_id and security_level
    """
    LOGGER.info("Update Alarm Status")
    site_id = message.get("site_id")
    security_level = message.get("security_level")
    payload = {"security_level": ALARM_STATUS.get(security_level, "disarmed")}
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)


def handle_alarm_trespass(ws, message: dict) -> None:
    """Handle intrusion alarm triggered.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing alarm details
    """
    LOGGER.info("Report Alarm Triggered")
    site_id = message.get("site_id")
    device_id = message.get("device_id")
    device_type = message.get("device_type")
    
    if message.get("type") != "alarm":
        LOGGER.info(f"{message.get('type')} is not 'alarm'")
    
    # Set alarm to triggered state
    payload = {"security_level": "triggered"}
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)

    # If triggered by PIR sensor, send motion event
    if device_type == "pir":
        LOGGER.info("Trigger PIR Sensor")
        topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/pir"
        mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"motion_sensor": "True"}, retain=True)
        time.sleep(3)
        mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload={"motion_sensor": "False"}, retain=True)


def handle_alarm_panic(ws, message: dict) -> None:
    """Handle panic alarm triggered.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id
    """
    LOGGER.info("Report Alarm Panic")
    site_id = message.get("site_id")
    payload = {"security_level": "triggered"}
    topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"
    mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)


def handle_alarm_domestic_fire(ws, message: dict) -> None:
    """Handle fire/smoke alarm triggered.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id and device list
    """
    LOGGER.info("Report Alarm Fire")
    site_id = message.get("site_id")
    payload = {"smoke": "True"}
    
    for device_id in message.get("devices", []):
        topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/fire"
        mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)


def handle_alarm_domestic_fire_end(ws, message: dict) -> None:
    """Handle fire/smoke alarm cleared.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id and device list
    """
    LOGGER.info("Report Alarm Fire End")
    site_id = message.get("site_id")
    payload = {"smoke": "False"}
    
    for device_id in message.get("devices", []):
        topic = f"{ws.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/fire"
        mqtt_publish(mqtt_client=ws.mqtt_client, topic=topic, payload=payload, retain=True)


def handle_alarm_end(ws, message: dict) -> None:
    """Handle alarm stopped.
    
    Args:
        ws: WebSocket instance
        message: WebSocket message containing site_id
    """
    LOGGER.info("Report Alarm Stop")
    site_id = message.get("site_id")
    update_site(ws.api, ws.mqtt_client, ws.mqtt_config, site_id)
