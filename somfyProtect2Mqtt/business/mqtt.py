"""MQTT Business"""

import json
import logging
from time import sleep
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Tuple

from homeassistant.ha_discovery import ALARM_STATUS
from paho.mqtt import client
from somfy_protect.api import ACCESS_LIST, ACTION_LIST, SomfyProtectApi

LOGGER = logging.getLogger(__name__)
# Use set instead of list to prevent duplicates
SUBSCRIBE_TOPICS: set = set()

# Executor for background tasks to avoid unbounded thread creation
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def parse_mqtt_topic(topic: str, min_parts: int = 3) -> Optional[Tuple[str, ...]]:
    """Parse MQTT topic safely.
    
    Args:
        topic: MQTT topic string
        min_parts: Minimum number of parts expected
        
    Returns:
        Tuple of topic parts if valid, None otherwise
    """
    parts = topic.split("/")
    if len(parts) < min_parts:
        LOGGER.warning(f"Invalid MQTT topic format (expected >={min_parts} parts): {topic}")
        return None
    return tuple(parts)


def submit_delayed(func: Callable, delay: int = 1, *args, **kwargs):
    """Submit a call to `func` run after `delay` seconds in the shared executor.

    Returns the Future.
    """

    def _wrap():
        sleep(delay)
        return func(*args, **kwargs)

    return _EXECUTOR.submit(_wrap)


def shutdown_executor(timeout: int = 5) -> None:
    """Shutdown the shared executor gracefully.

    This should be called at application shutdown to allow background
    tasks to complete.
    """
    try:
        _EXECUTOR.shutdown(wait=True)
    except Exception:
        LOGGER.exception("Error while shutting down executor")


def mqtt_publish(mqtt_client, topic, payload, qos=0, retain=False, is_json=True):
    """MQTT publish"""
    if is_json:
        payload = json.dumps(payload, ensure_ascii=False).encode("utf8")
    mqtt_client.client.publish(topic, payload, qos=qos, retain=retain)


def update_device(api, mqtt_client, mqtt_config, site_id, device_id):
    """Update MQTT data for a device"""
    LOGGER.info(f"Live Update device {device_id}")
    try:
        device = api.get_device(site_id=site_id, device_id=device_id)
        settings = device.settings.get("global")
        status = device.status
        status_settings = {**status, **settings}

        # Convert Values to String
        keys_values = status_settings.items()
        payload = {str(key): str(value) for key, value in keys_values}
        # Push status to MQTT
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
            payload=payload,
            retain=True,
        )
    except Exception as exp:
        LOGGER.warning(f"Error while refreshing device {device_id}: {exp}")


def update_site(api, mqtt_client, mqtt_config, site_id):
    """Update MQTT data for a site"""
    LOGGER.info(f"Live Update site {site_id}")
    try:
        site = api.get_site(site_id=site_id)
        # Push status to MQTT
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
            payload={"security_level": ALARM_STATUS.get(site.security_level, "disarmed")},
            retain=True,
        )
    except Exception as exp:
        LOGGER.warning(f"Error while refreshing site {site_id}: {exp}")


def consume_mqtt_message(msg, mqtt_config: dict, api: SomfyProtectApi, mqtt_client: client):
    """Compute MQTT received message"""
    try:
        text_payload = msg.payload.decode("UTF-8")
        LOGGER.info(f"Payload {text_payload}")

        # Manage Alarm Status
        if text_payload in ALARM_STATUS:
            LOGGER.info(f"Security Level update ! Setting to {text_payload}")
            parts = parse_mqtt_topic(msg.topic, min_parts=2)
            if not parts:
                return
            site_id = parts[1]
            LOGGER.debug(f"Site ID: {site_id}")
            
            # Update Alarm via API
            api.update_security_level(site_id=site_id, security_level=text_payload)

            # Read updated Alarm Status in background
            def update_site_delayed():
                sleep(1)
                update_site(
                    api=api,
                    mqtt_client=mqtt_client,
                    mqtt_config=mqtt_config,
                    site_id=site_id,
                )

            # schedule via shared executor to avoid unlimited threads
            submit_delayed(update_site_delayed)

        # Manage Siren
        elif text_payload.lower() in ("panic", "trigger"):
            parts = parse_mqtt_topic(msg.topic, min_parts=2)
            if not parts:
                return
            site_id = parts[1]
            LOGGER.info(f"Start the Siren On Site ID {site_id}")
            api.trigger_alarm(site_id=site_id, mode="alarm")

        elif text_payload == "stop":
            parts = parse_mqtt_topic(msg.topic, min_parts=2)
            if not parts:
                return
            site_id = parts[1]
            LOGGER.info(f"Stop the Siren On Site ID {site_id}")
            api.stop_alarm(site_id=site_id)

        elif text_payload in [
            "evostream",
            "webrtc",
        ]:
            parts = parse_mqtt_topic(msg.topic, min_parts=3)
            if not parts:
                return
            site_id, device_id = parts[1], parts[2]
            LOGGER.info(f"Update Video Backend To ({text_payload})")
            action_device = api.action_device(
                site_id=site_id, device_id=device_id, action="change_video_backend", video_backend=text_payload
            )

        elif text_payload in [
            "test_smokeExtended",
            "test_siren1s",
            "test_armed",
            "test_disarmed",
            "test_intrusion",
            "test_ok",
        ]:
            parts = parse_mqtt_topic(msg.topic, min_parts=3)
            if not parts:
                return
            site_id, device_id = parts[1], parts[2]
            sound = text_payload.split("_")[1]
            LOGGER.info(f"Test the Siren On Site ID {site_id} ({sound})")
            api.test_siren(site_id=site_id, device_id=device_id, sound=sound)

        # Manage Access
        elif text_payload in ACCESS_LIST:
            parts = parse_mqtt_topic(msg.topic, min_parts=3)
            if not parts:
                return
            site_id, device_id = parts[1], parts[2]
            if device_id:
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Access: {text_payload}")
                trigger_access = api.trigger_access(
                    site_id=site_id,
                    device_id=device_id,
                    access=text_payload,
                )
                LOGGER.debug(trigger_access)

        # Manage Actions
        elif text_payload in ACTION_LIST:
            parts = parse_mqtt_topic(msg.topic, min_parts=3)
            if not parts:
                return
            site_id, device_id = parts[1], parts[2]
            if device_id:
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Action: {text_payload}")
                action_device = api.action_device(
                    site_id=site_id,
                    device_id=device_id,
                    action=text_payload,
                )
                LOGGER.debug(action_device)

                # Read updated device in background
                def update_device_delayed():
                    sleep(1)
                    update_device(
                        api=api,
                        mqtt_client=mqtt_client,
                        mqtt_config=mqtt_config,
                        site_id=site_id,
                        device_id=device_id,
                    )

                submit_delayed(update_device_delayed)
            else:
                LOGGER.info(f"Message received for Site ID: {site_id}, Action: {text_payload}")

        # Manage Manual Snapshot
        else:
            parts = parse_mqtt_topic(msg.topic, min_parts=4)
            if not parts:
                return
            site_id, device_id, setting = parts[1], parts[2], parts[3]
            
            if setting == "snapshot":
                if text_payload.lower() in ("true", "1", "on"):
                    LOGGER.info("Manual Snapshot")
                    api.camera_refresh_snapshot(site_id=site_id, device_id=device_id)
                    response = api.camera_snapshot(site_id=site_id, device_id=device_id)
                    if response and getattr(response, "status_code", None) == 200:
                        # Read response content into memory safely using .iter_content
                        try:
                            from io import BytesIO

                            buf = BytesIO()
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    buf.write(chunk)
                            image_bytes = buf.getvalue()
                            topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                            mqtt_publish(
                                mqtt_client,
                                topic,
                                image_bytes,
                                retain=True,
                                is_json=False,
                                qos=2,
                            )
                        finally:
                            try:
                                response.close()
                            except Exception:
                                pass
                return

            # Manage Settings update (fallback)
            elif setting != "stream":
                # Convert Boolean strings to actual booleans
                if text_payload == "True":
                    text_payload = bool(True)
                elif text_payload == "False":
                    text_payload = bool(False)

                device = api.get_device(site_id=site_id, device_id=device_id)
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Setting: {setting}")
                settings = device.settings
                settings["global"][setting] = text_payload
                # Remove null values from settings before sending to API
                settings = {k: v for k, v in settings.items() if v is not None}
                # If setting is night_vision, remove other global settings except night_vision
                if setting == "night_vision":
                    settings["global"] = {"night_vision": text_payload}
                api.update_device(
                    site_id=site_id,
                    device_id=device_id,
                    device_label=device.label,
                    settings=settings,
                )

                # Read updated device in background
                def update_device_delayed():
                    sleep(1)
                    update_device(
                        api=api,
                        mqtt_client=mqtt_client,
                        mqtt_config=mqtt_config,
                        site_id=site_id,
                        device_id=device_id,
                    )

                submit_delayed(update_device_delayed)

    except Exception as exp:
        LOGGER.error(f"Error when processing message: {exp}: {msg.topic} => {msg.payload}")
