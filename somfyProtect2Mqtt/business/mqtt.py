"""MQTT Business"""

import json
import logging
import threading
from time import sleep

from homeassistant.ha_discovery import ALARM_STATUS
from paho.mqtt import client
from requests import RequestException
from somfy_protect.api import ACCESS_LIST, ACTION_LIST, SomfyProtectApi

# from business.streaming import rtmps_to_hls

LOGGER = logging.getLogger(__name__)
SUBSCRIBE_TOPICS = []


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


def mqtt_publish(mqtt_client, topic, payload, qos=0, retain=False, is_json=True):
    """MQTT publish"""
    if is_json:
        payload = json.dumps(payload, ensure_ascii=False).encode("utf8")
    mqtt_client.client.publish(topic, payload, qos=qos, retain=retain)


def update_device(api, mqtt_client, mqtt_config, site_id, device_id):
    """Update MQTT data for a device"""
    LOGGER.info("Live Update device {}".format(device_id))
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
        LOGGER.warning("Error while refreshing {}: {}".format(device_label, e))


def update_site(api, mqtt_client, mqtt_config, site_id):
    """Update MQTT data for a site"""
    LOGGER.info("Live Update site {}".format(site_id))
    try:
        site = api.get_site(site_id=site_id)
        # Push status to MQTT
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
            payload={"security_level": ALARM_STATUS.get(site.security_level, "disarmed")},
            retain=True,
        )
    except (RequestException, AttributeError, KeyError, ValueError) as e:
        LOGGER.warning("Error while refreshing site {}: {}".format(site_id, e))


def consume_mqtt_message(msg, mqtt_config: dict, api: SomfyProtectApi, mqtt_client: client):
    """Compute MQTT received message"""
    try:
        text_payload = msg.payload.decode("UTF-8")
        lower_payload = text_payload.lower()
        LOGGER.info("Payload {}".format(text_payload))
        topic_parts = msg.topic.split("/")

        def require_parts(min_parts: int, context: str) -> bool:
            if len(topic_parts) < min_parts:
                LOGGER.warning("Invalid topic format for {}: {}".format(context, msg.topic))
                return False
            return True

        if not require_parts(2, "site"):
            return
        # Manage Alarm Status
        if text_payload in ALARM_STATUS:
            LOGGER.info("Security Level update ! Setting to {}".format(text_payload))
            site_id = topic_parts[1]
            LOGGER.debug("Site ID: {}".format(site_id))
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

            thread = threading.Thread(target=update_site_delayed)
            thread.daemon = True
            thread.start()

        # Manage Siren
        elif lower_payload in ("panic", "trigger"):
            site_id = topic_parts[1]
            LOGGER.info("Start the Siren On Site ID {}".format(site_id))
            api.trigger_alarm(site_id=site_id, mode="alarm")

        elif text_payload == "stop":
            site_id = topic_parts[1]
            LOGGER.info("Stop the Siren On Site ID {}".format(site_id))
            api.stop_alarm(site_id=site_id)

        elif text_payload in [
            "evostream",
            "webrtc",
        ]:
            if not require_parts(3, "device"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            LOGGER.info("Update Video Backend To ({})".format(text_payload))
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
            if not require_parts(3, "device"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            sound = text_payload.split("_")[1]
            LOGGER.info("Test the Siren On Site ID {} ({})".format(site_id, sound))
            api.test_siren(site_id=site_id, device_id=device_id, sound=sound)

        # Manage Access
        elif text_payload in ACCESS_LIST:
            if not require_parts(3, "device"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            if device_id:
                LOGGER.info(
                    "Message received for Site ID: {}, Device ID: {}, Access: {}".format(
                        site_id,
                        device_id,
                        text_payload,
                    )
                )
                trigger_access = api.trigger_access(
                    site_id=site_id,
                    device_id=device_id,
                    access=text_payload,
                )
                LOGGER.debug(trigger_access)

        # Manage Actions
        elif text_payload in ACTION_LIST:
            if not require_parts(3, "device"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            if device_id:
                LOGGER.info(
                    "Message received for Site ID: {}, Device ID: {}, Action: {}".format(
                        site_id,
                        device_id,
                        text_payload,
                    )
                )
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

                thread = threading.Thread(target=update_device_delayed)
                thread.daemon = True
                thread.start()
            else:
                LOGGER.info("Message received for Site ID: {}, Action: {}".format(site_id, text_payload))

        # Manage Manual Snapshot
        elif len(topic_parts) > 3 and topic_parts[3] == "snapshot":
            if not require_parts(3, "device"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            if lower_payload in ("true", "1", "yes", "on"):
                LOGGER.info("Manual Snapshot")
                api.camera_refresh_snapshot(site_id=site_id, device_id=device_id)
                response = api.camera_snapshot(site_id=site_id, device_id=device_id)
                if response is None:
                    LOGGER.warning("Snapshot response missing")
                    return
                if response.status_code == 200:
                    # Write image to temp file
                    path = f"{device_id}.jpeg"
                    with open(path, "wb") as snapshot_file:
                        for chunk in response:
                            snapshot_file.write(chunk)
                    # Read and Push to MQTT
                    snapshot_file = open(path, "rb")
                    image = snapshot_file.read()
                    byte_array = bytearray(image)
                    topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                    mqtt_publish(
                        mqtt_client,
                        topic,
                        byte_array,
                        retain=True,
                        is_json=False,
                        qos=2,
                    )

        # Manage Settings update
        else:
            if not require_parts(4, "setting"):
                return
            site_id = topic_parts[1]
            device_id = topic_parts[2]
            setting = topic_parts[3]
            if setting == "stream":
                return

            # Convert Boolean strings to actual booleans
            if text_payload == "True":
                text_payload = bool(True)
            elif text_payload == "False":
                text_payload = bool(False)

            device = api.get_device(site_id=site_id, device_id=device_id)
            LOGGER.info(
                "Message received for Site ID: {}, Device ID: {}, Setting: {}".format(
                    site_id,
                    device_id,
                    setting,
                )
            )
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

            thread = threading.Thread(target=update_device_delayed)
            thread.daemon = True
            thread.start()

    except (RequestException, AttributeError, KeyError, ValueError) as e:
        LOGGER.error("Error when processing message: {}: {} => {}".format(e, msg.topic, msg.payload))
