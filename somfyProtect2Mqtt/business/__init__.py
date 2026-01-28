"""Business Functions"""

import logging
import os
from datetime import datetime, timedelta
import pytz
from time import sleep

import schedule
from business.mqtt import mqtt_publish, SUBSCRIBE_TOPICS
from business.watermark import insert_watermark
from exceptions import SomfyProtectInitError
from http.client import RemoteDisconnected
from homeassistant.ha_discovery import (
    ALARM_STATUS,
    DEVICE_CAPABILITIES,
    ha_discovery_alarm,
    ha_discovery_alarm_actions,
    ha_discovery_history,
    ha_discovery_cameras,
    ha_discovery_devices,
)
from mqtt import MQTTClient
import requests
from somfy_protect.api import SomfyProtectApi
from somfy_protect.api.devices.category import Category

LOGGER = logging.getLogger(__name__)

DEVICE_TAG = {}
HISTORY = {}


def ha_sites_config(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    homeassistant_config: dict,
    my_sites_id: list,
) -> None:
    """HA Site Config"""
    LOGGER.info("Looking for Sites")
    for site_id in my_sites_id:
        # Alarm Status
        my_site = api.get_site(site_id=site_id)
        site = ha_discovery_alarm(
            site=my_site,
            mqtt_config=mqtt_config,
            homeassistant_config=homeassistant_config,
        )
        site_extended = ha_discovery_alarm_actions(site=my_site, mqtt_config=mqtt_config)
        configs = [site, site_extended]
        for site_config in configs:
            mqtt_publish(
                mqtt_client=mqtt_client,
                topic=site_config.get("topic"),
                payload=site_config.get("config"),
                retain=True,
            )
            mqtt_client.client.subscribe(site_config.get("config").get("command_topic"))
            SUBSCRIBE_TOPICS.append(site_config.get("config").get("command_topic"))

            history = ha_discovery_history(
                site=my_site,
                mqtt_config=mqtt_config,
            )
            configs = [history]
            for history_config in configs:
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=history_config.get("topic"),
                    payload=history_config.get("config"),
                    retain=True,
                )

        try:
            scenarios_core = api.get_scenarios_core(site_id=my_site.id)
            LOGGER.info(f"Scenarios Core for {my_site.label} => {scenarios_core}")
            scenarios = api.get_scenarios(site_id=my_site.id)
            LOGGER.info(f"Scenarios for {my_site.label} => {scenarios}")
            LOGGER.warning(f"v4 => {api.get_site_scenario(site_id=site_id)}")
        except Exception as exp:
            LOGGER.warning(f"Error while getting scenarios: {exp}")
            continue


def convert_utc_to_paris(date: datetime) -> datetime:

    utc_zone = pytz.utc
    date = utc_zone.localize(date)
    paris_zone = pytz.timezone("Europe/Paris")
    paris_date = date.astimezone(paris_zone)
    return paris_date


def ha_devices_config(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    my_sites_id: list,
) -> None:
    """HA Devices Config"""
    LOGGER.info("Looking for Devices")
    for site_id in my_sites_id:
        my_devices = api.get_devices(site_id=site_id)
        for device in my_devices:
            LOGGER.info(f"Configuring Device: {device.label}")
            settings = device.settings.get("global")
            status = device.status
            status_settings = {**status, **settings}

            for state in status_settings:
                if not DEVICE_CAPABILITIES.get(state):
                    LOGGER.debug(f"No Config for {state}")
                    continue
                device_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name=state,
                )
                if state in ["human_detect_enabled"]:
                    mqtt_publish(
                        mqtt_client=mqtt_client,
                        topic=device_config.get("topic"),
                        payload={},
                        retain=True,
                    )
                else:
                    mqtt_publish(
                        mqtt_client=mqtt_client,
                        topic=device_config.get("topic"),
                        payload=device_config.get("config"),
                        retain=True,
                    )

                if device_config.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(device_config.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(device_config.get("config").get("command_topic"))

            if "box" in device.device_definition.get("type"):
                LOGGER.info(f"Found Link {device.device_definition.get('label')}")
                reboot = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="reboot",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=reboot.get("topic"),
                    payload=reboot.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(reboot.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(reboot.get("config").get("command_topic"))

                halt = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="halt",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=halt.get("topic"),
                    payload=halt.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(halt.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(halt.get("config").get("command_topic"))

            if "camera" in device.device_definition.get("type") or "allinone" in device.device_definition.get("type"):
                LOGGER.info(f"Found Camera {device.device_definition.get('label')}")
                camera_config = ha_discovery_cameras(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=camera_config.get("topic"),
                    payload=camera_config.get("config"),
                    retain=True,
                )
                reboot = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="reboot",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=reboot.get("topic"),
                    payload=reboot.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(reboot.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(reboot.get("config").get("command_topic"))

                halt = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="halt",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=halt.get("topic"),
                    payload=halt.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(halt.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(halt.get("config").get("command_topic"))

                # Manual Snapshot
                device_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="snapshot",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=device_config.get("topic"),
                    payload=device_config.get("config"),
                    retain=True,
                )
                if device_config.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(device_config.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(device_config.get("config").get("command_topic"))

                # Video Backend
                video_backend = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="video_backend",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=video_backend.get("topic"),
                    payload=video_backend.get("config"),
                    retain=True,
                )
                if video_backend.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(video_backend.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(video_backend.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/video_backend"
                    )

                # Stream
                stream = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="stream",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=stream.get("topic"),
                    payload=stream.get("config"),
                    retain=True,
                )
                if stream.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(stream.get("config").get("command_topic"))
                    mqtt_client.client.subscribe(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/stream"
                    )
                    SUBSCRIBE_TOPICS.append(stream.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/stream"
                    )

            # Works with Websockets
            if "remote" in device.device_definition.get("type"):
                LOGGER.info(f"Found {device.device_definition.get('label')}")
                key_fob_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="presence",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=key_fob_config.get("topic"),
                    payload=key_fob_config.get("config"),
                    retain=True,
                )
            if "mss_outdoor_siren" in device.device_definition.get("device_definition_id"):
                mss_outdoor_siren = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="test_siren1s",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=mss_outdoor_siren.get("topic"),
                    payload=mss_outdoor_siren.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(mss_outdoor_siren.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(mss_outdoor_siren.get("config").get("command_topic"))

            if "mss_siren" in device.device_definition.get("device_definition_id"):
                for sensor in [
                    "smokeExtended",
                    "siren1s",
                    "armed",
                    "disarmed",
                    "intrusion",
                    "ok",
                ]:
                    LOGGER.info(f"Found mss_siren, adding sound test: {sensor}")
                    mss_siren = ha_discovery_devices(
                        site_id=site_id,
                        device=device,
                        mqtt_config=mqtt_config,
                        sensor_name=f"test_{sensor}",
                    )
                    mqtt_publish(
                        mqtt_client=mqtt_client,
                        topic=mss_siren.get("topic"),
                        payload=mss_siren.get("config"),
                        retain=True,
                    )
                mqtt_client.client.subscribe(mss_siren.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(mss_siren.get("config").get("command_topic"))

            if "pir" in device.device_definition.get("type") or "tag" in device.device_definition.get("type"):
                LOGGER.info(f"Found Motion Sensor (PIR & IntelliTag) {device.device_definition.get('label')}")
                pir_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="motion_sensor",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=pir_config.get("topic"),
                    payload=pir_config.get("config"),
                    retain=True,
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=pir_config.get("config").get("state_topic"),
                    payload={"motion_sensor": "False"},
                    retain=True,
                )

            if "smoke" in device.device_definition.get("type"):
                LOGGER.info(f"Found {device.device_definition.get('label')}")
                smoke_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="smoke",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=smoke_config.get("topic"),
                    payload=smoke_config.get("config"),
                    retain=True,
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=smoke_config.get("config").get("state_topic"),
                    payload={"smoke": "False"},
                    retain=True,
                )

            if device.device_definition.get("type") == "doorlock":
                LOGGER.info(f"DoorLock {device.device_definition.get('label')}")

                open_door = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="open_door",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=open_door.get("topic"),
                    payload=open_door.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(open_door.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(open_door.get("config").get("command_topic"))

                door_force_Lock = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="door_force_Lock",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=door_force_Lock.get("topic"),
                    payload=door_force_Lock.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(door_force_Lock.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(door_force_Lock.get("config").get("command_topic"))

            if "videophone" in device.device_definition.get("type"):
                LOGGER.info(f"VideoPhone {device.device_definition.get('label')}")
                camera_config = ha_discovery_cameras(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=camera_config.get("topic"),
                    payload=camera_config.get("config"),
                    retain=True,
                )
                ringing_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="ringing",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=ringing_config.get("topic"),
                    payload=ringing_config.get("config"),
                    retain=True,
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=ringing_config.get("config").get("state_topic"),
                    payload={"ringing": "False"},
                    retain=True,
                )

                reboot = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="reboot",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=reboot.get("topic"),
                    payload=reboot.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(reboot.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(reboot.get("config").get("command_topic"))

                halt = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="halt",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=halt.get("topic"),
                    payload=halt.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(halt.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(halt.get("config").get("command_topic"))

                open_latch = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="open_latch",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=open_latch.get("topic"),
                    payload=open_latch.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(open_latch.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(open_latch.get("config").get("command_topic"))

                open_gate = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="open_gate",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=open_gate.get("topic"),
                    payload=open_gate.get("config"),
                    retain=True,
                )
                mqtt_client.client.subscribe(open_gate.get("config").get("command_topic"))
                SUBSCRIBE_TOPICS.append(open_gate.get("config").get("command_topic"))

                # Manual Snapshot
                device_config = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="snapshot",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=device_config.get("topic"),
                    payload=device_config.get("config"),
                    retain=True,
                )
                if device_config.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(device_config.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(device_config.get("config").get("command_topic"))

                # Stream
                stream = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="stream",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=stream.get("topic"),
                    payload=stream.get("config"),
                    retain=True,
                )
                if stream.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(stream.get("config").get("command_topic"))
                    mqtt_client.client.subscribe(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/stream"
                    )
                    SUBSCRIBE_TOPICS.append(stream.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/stream"
                    )

                # Video Backend
                video_backend = ha_discovery_devices(
                    site_id=site_id,
                    device=device,
                    mqtt_config=mqtt_config,
                    sensor_name="video_backend",
                )
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=video_backend.get("topic"),
                    payload=video_backend.get("config"),
                    retain=True,
                )
                if video_backend.get("config").get("command_topic"):
                    mqtt_client.client.subscribe(video_backend.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(video_backend.get("config").get("command_topic"))
                    SUBSCRIBE_TOPICS.append(
                        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/video_backend"
                    )


def update_sites_status(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    my_sites_id: list,
) -> None:
    """Uodate Devices Status (Including zone)"""
    LOGGER.info("Update Sites Status")
    for site_id in my_sites_id:
        try:
            site = api.get_site(site_id=site_id)
            LOGGER.info(f"Update {site.label} Status")

            try:
                # Push status to MQTT
                mqtt_publish(
                    mqtt_client=mqtt_client,
                    topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
                    payload={"security_level": ALARM_STATUS.get(site.security_level, "disarmed")},
                    retain=True,
                )
            except Exception as exp:
                LOGGER.warning(f"Error while updating MQTT: {exp}")
                continue
        except RemoteDisconnected as exp:
            LOGGER.info(f"Retrying...")
        except Exception as exp:
            LOGGER.warning(f"Error while refreshing site: {exp}")
            continue

        try:
            payload = {}
            events = api.get_history(site_id=site_id)
            for event in events:
                if event:
                    occurred_at = event.get("occurred_at")
                    date_format = "%Y-%m-%dT%H:%M:%S.%fZ"
                    occurred_at_date = datetime.strptime(occurred_at, date_format)
                    occurred_at_date = convert_utc_to_paris(date=occurred_at_date)
                    paris_tz = pytz.timezone("Europe/Paris")
                    now = datetime.now(paris_tz)
                    if now - occurred_at_date < timedelta(seconds=3600):
                        if occurred_at in HISTORY:
                            LOGGER.debug(f"History still published: {HISTORY[occurred_at]}")
                            continue
                        payload = f"{event.get('message_key')} {event.get('message_vars').get('userDsp')} {event.get('message_vars').get('siteLabel')}"
                        payload = payload.replace("None", "").strip().strip('"').replace(".", " ").title()
                        HISTORY[occurred_at] = payload
                        LOGGER.info(f"Publishing History: {HISTORY[occurred_at]}")
                        mqtt_publish(
                            mqtt_client=mqtt_client,
                            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/history",
                            payload=payload,
                            retain=True,
                        )
                    else:
                        LOGGER.debug(
                            f"Event is too old {event.get('message_key')} {event.get('message_vars').get('userDsp')} {event.get('message_vars').get('siteLabel')}"
                        )

        except Exception as exp:
            LOGGER.warning(f"Error while getting site history: {exp}")
            continue

        except Exception as exp:
            LOGGER.warning(f"Error while refreshing site: {exp}")
            continue


def update_devices_status(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    my_sites_id: list,
) -> None:
    """Update Devices Status (Including zone)"""
    LOGGER.info("Update Devices Status")
    for site_id in my_sites_id:
        try:
            my_devices = api.get_devices(site_id=site_id)
            for device in my_devices:
                device_type = device.device_definition.get("type", "")
                if "camera" in device_type or "allinone" in device_type or "videophone" in device_type:
                    video_backend = device.video_backend
                    mqtt_publish(
                        mqtt_client=mqtt_client,
                        topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/video_backend",
                        payload={"video_backend": video_backend},
                        retain=True,
                    )

                if "videophone" in device.device_definition.get("type"):
                    events = api.get_device_events(site_id=site_id, device_id=device.id)
                    if events:
                        send_to_mqtt = True
                        for event in events:
                            if event.get("clip_cloudfront_url"):
                                LOGGER.info(f"Found a video: {event.get('clip_cloudfront_url')}")
                                write_to_media_folder(
                                    url=event.get("clip_cloudfront_url"),
                                    site_id=site_id,
                                    device_id=device.id,
                                    label=device.device_definition.get("label"),
                                    event_id=event.get("event_id"),
                                    occurred_at=event.get("occurred_at"),
                                    media_type="video",
                                    mqtt_client=mqtt_client,
                                    mqtt_config=mqtt_config,
                                )
                            if event.get("snapshot_cloudfront_url"):
                                LOGGER.info(f"Found a snapshot {event.get('snapshot_cloudfront_url')}")
                                write_to_media_folder(
                                    url=event.get("snapshot_cloudfront_url"),
                                    site_id=site_id,
                                    device_id=device.id,
                                    label=device.device_definition.get("label"),
                                    event_id=event.get("event_id"),
                                    occurred_at=event.get("occurred_at"),
                                    media_type="snapshot",
                                    mqtt_client=mqtt_client,
                                    mqtt_config=mqtt_config,
                                    send_to_mqtt=send_to_mqtt,
                                )

                settings = device.settings.get("global")
                if device.settings.get("global").get("user_id"):
                    DEVICE_TAG[device.settings.get("global").get("user_id")] = device.id
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
            LOGGER.warning(f"Error while refreshing devices: {exp}")
            continue


def update_camera_snapshot(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    my_sites_id: list,
) -> None:
    """Update Camera Snapshot"""
    LOGGER.info("Update Camera Snapshot")
    for site_id in my_sites_id:
        try:
            for category in [
                Category.INDOOR_CAMERA,
                Category.OUTDDOR_CAMERA,
                Category.MYFOX_CAMERA,
                Category.SOMFY_ONE_PLUS,
                Category.SOMFY_ONE,
            ]:
                my_devices = api.get_devices(site_id=site_id, category=category)
                for device in my_devices:
                    LOGGER.info(f"Shutter is {device.status.get('shutter_state', 'opened')}")
                    if device.status.get("shutter_state", "opened") != "closed":
                        api.camera_refresh_snapshot(site_id=site_id, device_id=device.id)
                        response = api.camera_snapshot(site_id=site_id, device_id=device.id)
                        if response.status_code == 200:
                            now = datetime.now()
                            timestamp = int(now.timestamp())

                            # Write image to temp file
                            path = f"{device.id}-{timestamp}.jpeg"
                            with open(path, "wb") as tmp_file:
                                for chunk in response:
                                    tmp_file.write(chunk)

                            # Add Watermark
                            insert_watermark(
                                file=f"{os.getcwd()}/{path}",
                                watermark=now.strftime("%Y-%m-%d %H:%M:%S"),
                            )

                            # Read and Push to MQTT
                            with open(path, "rb") as tmp_file:
                                image = tmp_file.read()
                            byte_arr = bytearray(image)
                            topic = (
                                f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/snapshot"
                            )
                            mqtt_publish(
                                mqtt_client=mqtt_client,
                                topic=topic,
                                payload=byte_arr,
                                retain=True,
                                is_json=False,
                            )

                            # Clean file
                            os.remove(path)

        except Exception as exp:
            LOGGER.warning(f"Error while refreshing snapshot: {exp}")
            continue


def update_visiophone_snapshot(
    url: str,
    site_id: str,
    device_id: str,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
) -> None:
    """Download VisioPhone Snapshot"""
    LOGGER.info("Download VisioPhone Snapshot")
    now = datetime.now()
    timestamp = int(now.timestamp())

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        path = f"{device_id}-{timestamp}.jpeg"
        with open(path, "wb") as tmp_file:
            for chunk in response.iter_content(1024):  # Lire en morceaux de 1 KB
                tmp_file.write(chunk)
    except requests.exceptions.RequestException as exc:
        LOGGER.warning(f"Error while Downloading snapshot: {exc}")

    # Add Watermark
    insert_watermark(
        file=f"{os.getcwd()}/{path}",
        watermark=now.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Read and Push to MQTT
    with open(path, "rb") as tmp_file:
        image = tmp_file.read()
    byte_arr = bytearray(image)
    topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
    mqtt_publish(
        mqtt_client=mqtt_client,
        topic=topic,
        payload=byte_arr,
        retain=True,
        is_json=False,
    )
    # Clean file
    os.remove(path)


def write_to_media_folder(
    url: str,
    site_id: str,
    device_id: str,
    label: str,
    event_id: str,
    occurred_at: str,
    media_type: str,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    send_to_mqtt: bool = False,
) -> None:
    """Download VisioPhone Clip"""
    LOGGER.info("Download VisioPhone Clip")
    directory = "/media/somfyprotect2mqtt"

    if media_type == "video":
        extention = "mp4"
    if media_type == "snapshot":
        extention = "jpeg"

    try:
        os.makedirs(directory, exist_ok=True)

        response = requests.get(url, stream=True)
        response.raise_for_status()

        path = f"{directory}/{label}-{occurred_at}-{event_id}.{extention}"

        with open(path, "wb") as file:
            for chunk in response.iter_content(1024):  # Lire en morceaux de 1 KB
                file.write(chunk)
        LOGGER.info(f"File wrote in {path}")

        if send_to_mqtt and media_type == "snapshot":
            # Read and Push to MQTT
            with open(path, "rb") as tmp_file:
                image = tmp_file.read()
            byte_arr = bytearray(image)
            topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
            mqtt_publish(
                mqtt_client=mqtt_client,
                topic=topic,
                payload=byte_arr,
                retain=True,
                is_json=False,
            )

    except OSError as exc:
        LOGGER.warning(f"Unable to create directory {directory}: {exc}")
    except requests.exceptions.RequestException as exc:
        LOGGER.warning(f"Error while Downloading clip: {exc}")
    finally:
        LOGGER.info("Write Successful")
