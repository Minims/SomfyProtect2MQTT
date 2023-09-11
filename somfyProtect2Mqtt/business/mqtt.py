""" MQTT Business"""
import json
import logging
from time import sleep

from homeassistant.ha_discovery import ALARM_STATUS
from paho.mqtt import client
from somfy_protect.api import ACTION_LIST, SomfyProtectApi

# from business.streaming import rtmps_to_hls

LOGGER = logging.getLogger(__name__)


def mqtt_publish(mqtt_client, topic, payload, qos=0, retain=False, is_json=True):
    """MQTT publish"""
    if is_json:
        payload = json.dumps(payload)
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
        LOGGER.warning(f"Error while refreshing {device.label}: {exp}")


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
        # # Manage Stream
        # if "rtmps" in text_payload:
        #     LOGGER.info("Start HLS")
        #     site_id = msg.topic.split("/")[1]
        #     device_id = msg.topic.split("/")[2]
        #     rtmps_to_hls(
        #         device_id=device_id,
        #         url=text_payload,
        #         path=os.getcwd(),
        #     )

        # Manage Boolean
        if text_payload == "True":
            text_payload = bool(True)

        elif text_payload == "False":
            text_payload = bool(False)

        # Manage Alarm Status
        elif text_payload in ALARM_STATUS:
            LOGGER.info(f"Security Level update ! Setting to {text_payload}")
            try:
                site_id = msg.topic.split("/")[1]
                LOGGER.debug(f"Site ID: {site_id}")
            except Exception as exp:
                LOGGER.warning(f"Unable to reteive Site ID: {site_id}: {exp}")
            # Update Alarm via API
            api.update_security_level(site_id=site_id, security_level=text_payload)
            # Read updated Alarm Status
            sleep(2)
            update_site(
                api=api,
                mqtt_client=mqtt_client,
                mqtt_config=mqtt_config,
                site_id=site_id,
            )

        # Manage Siren
        elif text_payload == "panic":
            site_id = msg.topic.split("/")[1]
            LOGGER.info(f"Start the Siren On Site ID {site_id}")
            api.trigger_alarm(site_id=site_id, mode="alarm")

        elif text_payload == "stop":
            site_id = msg.topic.split("/")[1]
            LOGGER.info(f"Stop the Siren On Site ID {site_id}")
            api.stop_alarm(site_id=site_id)

        elif text_payload in [
            "test_smokeExtended",
            "test_siren1s",
            "test_armed",
            "test_disarmed",
            "test_intrusion",
            "test_ok",
        ]:
            site_id = msg.topic.split("/")[1]
            device_id = msg.topic.split("/")[2]
            sound = text_payload.split("_")[1]
            LOGGER.info(f"Test the Siren On Site ID {site_id} ({sound})")
            api.test_siren(site_id=site_id, device_id=device_id, sound=sound)

        # Manage Actions
        elif text_payload in ACTION_LIST:
            site_id = msg.topic.split("/")[1]
            device_id = msg.topic.split("/")[2]
            if device_id:
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Action: {text_payload}")
                action_device = api.action_device(
                    site_id=site_id,
                    device_id=device_id,
                    action=text_payload,
                )
                LOGGER.debug(action_device)
                # Read updated device
                sleep(2)
                update_device(
                    api=api,
                    mqtt_client=mqtt_client,
                    mqtt_config=mqtt_config,
                    site_id=site_id,
                    device_id=device_id,
                )
            else:
                LOGGER.info(f"Message received for Site ID: {site_id}, Action: {text_payload}")

        # Manage Manual Snapshot
        elif msg.topic.split("/")[3] == "snapshot":
            site_id = msg.topic.split("/")[1]
            device_id = msg.topic.split("/")[2]
            if text_payload == "True":
                LOGGER.info("Manual Snapshot")
                api.camera_refresh_snapshot(site_id=site_id, device_id=device_id)
                response = api.camera_snapshot(site_id=site_id, device_id=device_id)
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
            site_id = msg.topic.split("/")[1]
            device_id = msg.topic.split("/")[2]
            setting = msg.topic.split("/")[3]
            if setting == "stream":
                return
            device = api.get_device(site_id=site_id, device_id=device_id)
            LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Setting: {setting}")
            settings = device.settings
            settings["global"][setting] = text_payload
            api.update_device(
                site_id=site_id,
                device_id=device_id,
                device_label=device.label,
                settings=settings,
            )
            # Read updated device
            sleep(2)
            update_device(
                api=api,
                mqtt_client=mqtt_client,
                mqtt_config=mqtt_config,
                site_id=site_id,
                device_id=device_id,
            )

    except Exception as exp:
        LOGGER.error(f"Error when processing message: {exp}: {msg.topic} => {msg.payload}")
