"""MQTT Business"""

import json
import logging
import threading
from dataclasses import dataclass

from business.tempfiles import remove_temp_file, write_temp_bytes
from homeassistant.ha_discovery import ALARM_STATUS
from paho.mqtt import client
from requests import RequestException
from somfy_protect.api import ACCESS_LIST, ACTION_LIST, TEST_SIREN_ACTIONS, SomfyProtectApi
from somfy_protect.api.model import AvailableStatus
from utils import parse_boolean

# from business.streaming import rtmps_to_hls

LOGGER = logging.getLogger(__name__)
SUBSCRIBE_TOPICS: set[str] = set()


def register_subscribe_topic(topic: str) -> None:
    """Register a topic for subscription without duplicates."""
    if topic:
        SUBSCRIBE_TOPICS.add(topic)


@dataclass
class MqttContext:
    """Context for MQTT message handling."""

    api: SomfyProtectApi
    mqtt_client: client
    mqtt_config: dict
    topic_parts: list


def build_device_status_payload(device) -> dict:
    """Build MQTT payload for a device status snapshot.

    Args:
        device: SomfyProtect device instance.

    Returns:
        dict: Serialized status payload.
    """
    settings = device.settings.get("global") or {}
    status = device.status
    status_settings = {**status, **settings}
    keys_values = status_settings.items()
    return {str(key): str(value) for key, value in keys_values}


def publish_site_state(mqtt_client, mqtt_config, site_id, security_level) -> None:
    """Publish site security level to MQTT."""
    mqtt_publish(
        mqtt_client=mqtt_client,
        topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
        payload={"security_level": ALARM_STATUS.get(security_level, "disarmed")},
        retain=True,
    )


def publish_device_state(mqtt_client, mqtt_config, site_id, device) -> None:
    """Publish device status payload to MQTT."""
    payload = build_device_status_payload(device)
    mqtt_publish(
        mqtt_client=mqtt_client,
        topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
        payload=payload,
        retain=True,
    )


def publish_snapshot_bytes(mqtt_client, mqtt_config, site_id, device_id, byte_arr) -> None:
    """Publish snapshot bytes to MQTT."""
    topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
    mqtt_publish(
        mqtt_client,
        topic,
        byte_arr,
        retain=True,
        is_json=False,
        qos=2,
    )


def _schedule_site_refresh(api, mqtt_client, mqtt_config, site_id) -> None:
    update_site(
        api=api,
        mqtt_client=mqtt_client,
        mqtt_config=mqtt_config,
        site_id=site_id,
    )


def _schedule_device_refresh(api, mqtt_client, mqtt_config, site_id, device_id) -> None:
    update_device(
        api=api,
        mqtt_client=mqtt_client,
        mqtt_config=mqtt_config,
        site_id=site_id,
        device_id=device_id,
    )


ALARM_COMMANDS = {k for k in ALARM_STATUS if k != "triggered"}


def _handle_alarm_status(text_payload, context: MqttContext) -> bool:
    if text_payload not in ALARM_COMMANDS:
        return False
    site_id = context.topic_parts[1]
    LOGGER.info(f"Security Level update ! Setting to {text_payload}")
    LOGGER.debug(f"Site ID: {site_id}")
    security_level = AvailableStatus[text_payload.upper()]
    context.api.update_security_level(site_id=site_id, security_level=security_level)
    threading.Timer(
        1.0, _schedule_site_refresh, args=(context.api, context.mqtt_client, context.mqtt_config, site_id)
    ).start()
    return True


def _handle_siren(text_payload, context: MqttContext) -> bool:
    if text_payload.lower() in ("panic", "trigger"):
        site_id = context.topic_parts[1]
        LOGGER.info(f"Start the Siren On Site ID {site_id}")
        context.api.trigger_alarm(site_id=site_id, mode="alarm")
        return True
    if text_payload == "stop":
        site_id = context.topic_parts[1]
        LOGGER.info(f"Stop the Siren On Site ID {site_id}")
        context.api.stop_alarm(site_id=site_id)
        return True
    return False


def _handle_video_backend(text_payload, context: MqttContext) -> bool:
    if text_payload not in ["evostream", "webrtc"]:
        return False
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    LOGGER.info(f"Update Video Backend To ({text_payload})")
    context.api.action_device(
        site_id=site_id,
        device_id=device_id,
        action="change_video_backend",
        video_backend=text_payload,
    )
    return True


def _handle_test_siren(text_payload, context: MqttContext) -> bool:
    if text_payload not in TEST_SIREN_ACTIONS:
        return False
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    sound = text_payload.split("_")[1]
    LOGGER.info(f"Test the Siren On Site ID {site_id} ({sound})")
    context.api.test_siren(site_id=site_id, device_id=device_id, sound=sound)
    return True


def _handle_access(text_payload, context: MqttContext) -> bool:
    if text_payload not in ACCESS_LIST:
        return False
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    if device_id:
        LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Access: {text_payload}")
        trigger_access = context.api.trigger_access(
            site_id=site_id,
            device_id=device_id,
            access=text_payload,
        )
        LOGGER.debug(trigger_access)
        threading.Timer(
            1.0,
            _schedule_device_refresh,
            args=(
                context.api,
                context.mqtt_client,
                context.mqtt_config,
                site_id,
                device_id,
            ),
        ).start()
    return True


def _handle_action(text_payload, context: MqttContext) -> bool:
    if text_payload not in ACTION_LIST:
        return False
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    if device_id:
        LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Action: {text_payload}")
        action_device = context.api.action_device(
            site_id=site_id,
            device_id=device_id,
            action=text_payload,
        )
        LOGGER.debug(action_device)
        threading.Timer(
            1.0,
            _schedule_device_refresh,
            args=(
                context.api,
                context.mqtt_client,
                context.mqtt_config,
                site_id,
                device_id,
            ),
        ).start()
    else:
        LOGGER.info(f"Message received for Site ID: {site_id}, Action: {text_payload}")
    return True


def _handle_snapshot(lower_payload, context: MqttContext) -> bool:
    if len(context.topic_parts) <= 3 or context.topic_parts[3] != "snapshot":
        return False
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    if not parse_boolean(lower_payload):
        return True
    LOGGER.info("Manual Snapshot")
    context.api.camera_refresh_snapshot(site_id=site_id, device_id=device_id)
    response = context.api.camera_snapshot(site_id=site_id, device_id=device_id)
    if response is None:
        LOGGER.warning("Snapshot response missing")
        return True
    if response.status_code == 200:
        path = None
        try:
            path = write_temp_bytes(response, suffix=".jpeg")
            with open(path, "rb") as snapshot_file:
                image = snapshot_file.read()
            byte_array = bytearray(image)
            publish_snapshot_bytes(context.mqtt_client, context.mqtt_config, site_id, device_id, byte_array)
        finally:
            remove_temp_file(path)
            response.close()
    return True


def _handle_setting(text_payload, context: MqttContext) -> None:
    site_id = context.topic_parts[1]
    device_id = context.topic_parts[2]
    setting = context.topic_parts[3]
    if setting == "stream":
        return
    if text_payload.lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        text_payload = parse_boolean(text_payload)
    device = context.api.get_device(site_id=site_id, device_id=device_id)
    LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Setting: {setting}")
    settings = device.settings
    settings.setdefault("global", {})[setting] = text_payload
    settings = {k: v for k, v in settings.items() if v is not None}
    if setting == "night_vision":
        settings["global"] = {"night_vision": text_payload}
    context.api.update_device(
        site_id=site_id,
        device_id=device_id,
        device_label=device.label,
        settings=settings,
    )
    threading.Timer(
        1.0,
        _schedule_device_refresh,
        args=(
            context.api,
            context.mqtt_client,
            context.mqtt_config,
            site_id,
            device_id,
        ),
    ).start()


def _requires_device_topic(text_payload, topic_parts) -> bool:
    if len(topic_parts) > 3 and topic_parts[3] == "snapshot":
        return True
    if text_payload in ["evostream", "webrtc"]:
        return True
    if text_payload in TEST_SIREN_ACTIONS:
        return True
    if text_payload in ACCESS_LIST:
        return True
    if text_payload in ACTION_LIST:
        return True
    return False


def mqtt_publish(mqtt_client, topic, payload, qos=0, retain=False, is_json=True):
    """MQTT publish"""
    if is_json:
        payload = json.dumps(payload, ensure_ascii=False).encode("utf8")
    mqtt_client.client.publish(topic, payload, qos=qos, retain=retain)


def update_device(api, mqtt_client, mqtt_config, site_id, device_id):
    """Update MQTT data for a device"""
    LOGGER.info(f"Live Update device {device_id}")
    device_label = device_id
    try:
        device = api.get_device(site_id=site_id, device_id=device_id)
        device_label = device.label
        payload = build_device_status_payload(device)
        # Push status to MQTT
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
            payload=payload,
            retain=True,
        )
    except (RequestException, AttributeError, KeyError, ValueError) as e:
        LOGGER.exception(f"Error while refreshing {device_label}: {e}")


def update_site(api, mqtt_client, mqtt_config, site_id):
    """Update MQTT data for a site"""
    LOGGER.info(f"Live Update site {site_id}")
    try:
        site = api.get_site(site_id=site_id)
        publish_site_state(mqtt_client, mqtt_config, site_id, site.security_level)
    except (RequestException, AttributeError, KeyError, ValueError) as e:
        LOGGER.exception(f"Error while refreshing site {site_id}: {e}")


def consume_mqtt_message(msg, mqtt_config: dict, api: SomfyProtectApi, mqtt_client: client):
    """Compute MQTT received message"""
    try:
        text_payload = msg.payload.decode("UTF-8")
        lower_payload = text_payload.lower()
        LOGGER.info(f"Payload {text_payload}")
        topic_parts = msg.topic.split("/")
        context = MqttContext(api=api, mqtt_client=mqtt_client, mqtt_config=mqtt_config, topic_parts=topic_parts)

        def require_parts(min_parts: int, context: str) -> bool:
            if len(topic_parts) < min_parts:
                LOGGER.warning(f"Invalid topic format for {context}: {msg.topic}")
                return False
            return True

        if not require_parts(2, "site"):
            return
        if _handle_alarm_status(text_payload, context):
            return
        if _handle_siren(text_payload, context):
            return
        if _requires_device_topic(text_payload, topic_parts):
            if not require_parts(3, "device"):
                return
        if _handle_video_backend(text_payload, context):
            return
        if _handle_test_siren(text_payload, context):
            return
        if _handle_access(text_payload, context):
            return
        if _handle_action(text_payload, context):
            return
        if _handle_snapshot(lower_payload, context):
            return
        if not require_parts(4, "setting"):
            return
        _handle_setting(text_payload, context)

    except (RequestException, AttributeError, KeyError, ValueError) as e:
        LOGGER.exception(f"Error when processing message: {e}: {msg.topic} => {msg.payload}")
