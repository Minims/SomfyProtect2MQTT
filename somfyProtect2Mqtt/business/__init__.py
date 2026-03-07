"""Business Functions"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from http.client import RemoteDisconnected
from time import sleep
from typing import TYPE_CHECKING, Optional

import pytz
import requests
import schedule
from business.mqtt import mqtt_publish, publish_device_state, publish_site_state, register_subscribe_topic
from business.watermark import insert_watermark
from constants import REQUEST_TIMEOUT, RETRY_STATUS_CODES
from exceptions import SomfyProtectInitError
from homeassistant.ha_discovery import (
    ALARM_STATUS,
    DEVICE_CAPABILITIES,
    ha_discovery_alarm,
    ha_discovery_alarm_actions,
    ha_discovery_cameras,
    ha_discovery_devices,
    ha_discovery_history,
)
from somfy_protect.api import SIREN_TEST_SOUNDS, SomfyProtectApi
from somfy_protect.api.devices.category import Category
from utils import build_retry_adapter

if TYPE_CHECKING:
    from mqtt import MQTTClient

LOGGER = logging.getLogger(__name__)

DEVICE_TAG = {}
HISTORY_LIMIT = 250
HISTORY: OrderedDict[str, str] = OrderedDict()
MEDIA_DIRECTORY = "/media/somfyprotect2mqtt"
MEDIA_INDEX_PATH = f"{MEDIA_DIRECTORY}/.processed_media.json"
MEDIA_INDEX_MAX_ENTRIES = 2000
PROCESSED_MEDIA_LOCK = threading.RLock()
PROCESSED_MEDIA: OrderedDict[str, str] = OrderedDict()
PROCESSED_MEDIA_LOADED = False


def _create_http_session() -> requests.Session:
    session = requests.Session()
    adapter = build_retry_adapter(RETRY_STATUS_CODES)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = _create_http_session()


def _load_processed_media_index() -> None:
    """Load the persisted media index once."""
    global PROCESSED_MEDIA_LOADED
    if PROCESSED_MEDIA_LOADED:
        return

    with PROCESSED_MEDIA_LOCK:
        if PROCESSED_MEDIA_LOADED:
            return
        try:
            with open(MEDIA_INDEX_PATH, "r", encoding="utf8") as index_file:
                entries = json.load(index_file)
        except (IOError, ValueError):
            entries = {}

        if isinstance(entries, dict):
            for media_key, timestamp in entries.items():
                if isinstance(media_key, str) and isinstance(timestamp, str):
                    PROCESSED_MEDIA[media_key] = timestamp
        _prune_processed_media_locked()
        PROCESSED_MEDIA_LOADED = True


def _prune_processed_media_locked() -> None:
    while len(PROCESSED_MEDIA) > MEDIA_INDEX_MAX_ENTRIES:
        PROCESSED_MEDIA.popitem(last=False)


def _persist_processed_media_locked() -> None:
    os.makedirs(MEDIA_DIRECTORY, exist_ok=True)
    with open(MEDIA_INDEX_PATH, "w", encoding="utf8") as index_file:
        json.dump(PROCESSED_MEDIA, index_file)


def build_media_dedupe_key(
    media_type: str,
    site_id: str,
    device_id: str,
    url: str,
    event_id: str | None = None,
    occurred_at: str | None = None,
) -> str:
    """Build a stable dedupe key for visiophone media."""
    stable_event_id = event_id or "unknown"
    stable_occurred_at = occurred_at or "unknown"
    return f"{media_type}:{site_id}:{device_id}:{stable_event_id}:{stable_occurred_at}:{url}"


def has_processed_media(media_key: str) -> bool:
    """Return True when a media item was already processed."""
    _load_processed_media_index()
    with PROCESSED_MEDIA_LOCK:
        return media_key in PROCESSED_MEDIA


def mark_media_processed(media_key: str) -> None:
    """Persist a media item as processed."""
    _load_processed_media_index()
    with PROCESSED_MEDIA_LOCK:
        if media_key in PROCESSED_MEDIA:
            PROCESSED_MEDIA.move_to_end(media_key)
        PROCESSED_MEDIA[media_key] = datetime.utcnow().isoformat()
        _prune_processed_media_locked()
        try:
            _persist_processed_media_locked()
        except OSError as e:
            LOGGER.warning("Unable to persist processed media index: {}".format(e))


def _publish_config(mqtt_client: MQTTClient, config: Optional[dict], payload: Optional[dict] = None) -> None:
    if not config:
        return
    mqtt_publish(
        mqtt_client=mqtt_client,
        topic=config.get("topic"),
        payload=payload if payload is not None else config.get("config"),
        retain=True,
    )


def _subscribe_command(mqtt_client: MQTTClient, config: Optional[dict]) -> None:
    if not config:
        return
    command_topic = config.get("config", {}).get("command_topic")
    if command_topic:
        mqtt_client.client.subscribe(command_topic)
        register_subscribe_topic(command_topic)


def _publish_and_subscribe(mqtt_client: MQTTClient, config: Optional[dict], payload: Optional[dict] = None) -> None:
    _publish_config(mqtt_client, config, payload=payload)
    _subscribe_command(mqtt_client, config)


def _publish_snapshot_command_topics(mqtt_config: dict, site_id: str, device_id: str) -> None:
    topic_prefix = mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    register_subscribe_topic(f"{topic_prefix}/{site_id}/{device_id}/video_backend")


def _publish_stream_command_topics(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device_id: str) -> None:
    topic_prefix = mqtt_config.get("topic_prefix", "somfyProtect2mqtt")
    stream_topic = f"{topic_prefix}/{site_id}/{device_id}/stream"
    mqtt_client.client.subscribe(stream_topic)
    register_subscribe_topic(stream_topic)


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
        for site_config in [site, site_extended]:
            _publish_and_subscribe(mqtt_client, site_config)

        history = ha_discovery_history(
            site=my_site,
            mqtt_config=mqtt_config,
        )
        _publish_config(mqtt_client, history)

        try:
            scenarios_core = api.get_scenarios_core(site_id=my_site.id)
            LOGGER.info("Scenarios Core for {} => {}".format(my_site.label, scenarios_core))
            scenarios = api.get_scenarios(site_id=my_site.id)
            LOGGER.info("Scenarios for {} => {}".format(my_site.label, scenarios))
            LOGGER.warning("v4 => {}".format(api.get_site_scenario(site_id=site_id)))
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            LOGGER.warning("Error while getting scenarios: {}".format(e))


def convert_utc_to_paris(date: datetime) -> datetime:
    """Convert a UTC datetime to Europe/Paris.

    Args:
        date (datetime): Naive UTC datetime.

    Returns:
        datetime: Timezone-aware datetime in Europe/Paris.
    """

    utc_zone = pytz.utc
    date = utc_zone.localize(date)
    paris_zone = pytz.timezone("Europe/Paris")
    paris_date = date.astimezone(paris_zone)
    return paris_date


def _configure_device_state_sensors(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device) -> None:
    settings = device.settings.get("global") or {}
    status = device.status
    status_settings = {**status, **settings}
    for state in status_settings:
        if not DEVICE_CAPABILITIES.get(state):
            LOGGER.debug("No Config for {}".format(state))
            continue
        device_config = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=state,
        )
        if state in ["human_detect_enabled"]:
            _publish_config(mqtt_client, device_config, payload={})
        else:
            _publish_config(mqtt_client, device_config)
        _subscribe_command(mqtt_client, device_config)


def _configure_box_device(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str) -> None:
    if "box" not in device_type:
        return
    LOGGER.info("Found Link {}".format(device.device_definition.get("label")))
    for action in ["reboot", "halt"]:
        config = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=action,
        )
        _publish_and_subscribe(mqtt_client, config)


def _configure_camera_device(
    mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str
) -> None:
    if "camera" not in device_type and "allinone" not in device_type:
        return
    LOGGER.info("Found Camera {}".format(device.device_definition.get("label")))
    camera_config = ha_discovery_cameras(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
    )
    _publish_config(mqtt_client, camera_config)
    for action in ["reboot", "halt"]:
        config = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=action,
        )
        _publish_and_subscribe(mqtt_client, config)
    device_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="snapshot",
    )
    _publish_and_subscribe(mqtt_client, device_config)
    video_backend = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="video_backend",
    )
    _publish_and_subscribe(mqtt_client, video_backend)
    if video_backend and video_backend.get("config", {}).get("command_topic"):
        _publish_snapshot_command_topics(mqtt_config, site_id, device.id)
    stream = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="stream",
    )
    _publish_and_subscribe(mqtt_client, stream)
    if stream and stream.get("config", {}).get("command_topic"):
        _publish_stream_command_topics(mqtt_client, mqtt_config, site_id, device.id)


def _configure_remote_device(
    mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str
) -> None:
    if "remote" not in device_type:
        return
    LOGGER.info("Found {}".format(device.device_definition.get("label")))
    key_fob_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="presence",
    )
    _publish_config(mqtt_client, key_fob_config)


def _configure_outdoor_siren(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device) -> None:
    if "mss_outdoor_siren" not in (device.device_definition.get("device_definition_id") or ""):
        return
    config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="test_siren1s",
    )
    _publish_and_subscribe(mqtt_client, config)


def _configure_siren(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device) -> None:
    if "mss_siren" not in (device.device_definition.get("device_definition_id") or ""):
        return
    mss_siren = None
    for sensor in SIREN_TEST_SOUNDS:
        LOGGER.info("Found mss_siren, adding sound test: {}".format(sensor))
        mss_siren = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=f"test_{sensor}",
        )
        _publish_config(mqtt_client, mss_siren)
        _subscribe_command(mqtt_client, mss_siren)


def _configure_motion_device(
    mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str
) -> None:
    if "pir" not in device_type and "tag" not in device_type:
        return
    LOGGER.info("Found Motion Sensor (PIR & IntelliTag) {}".format(device.device_definition.get("label")))
    pir_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="motion_sensor",
    )
    _publish_config(mqtt_client, pir_config)
    if pir_config:
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=pir_config.get("config", {}).get("state_topic"),
            payload={"motion_sensor": "False"},
            retain=True,
        )


def _configure_smoke_device(mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str) -> None:
    if "smoke" not in device_type:
        return
    LOGGER.info("Found {}".format(device.device_definition.get("label")))
    smoke_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="smoke",
    )
    _publish_config(mqtt_client, smoke_config)
    if smoke_config:
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=smoke_config.get("config", {}).get("state_topic"),
            payload={"smoke": "False"},
            retain=True,
        )


def _configure_doorlock_device(
    mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str
) -> None:
    if device_type != "doorlock":
        return
    LOGGER.info("DoorLock {}".format(device.device_definition.get("label")))
    for sensor_name in ["open_door", "door_force_lock"]:
        config = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=sensor_name,
        )
        _publish_and_subscribe(mqtt_client, config)


def _configure_videophone_device(
    mqtt_client: MQTTClient, mqtt_config: dict, site_id: str, device, device_type: str
) -> None:
    if "videophone" not in device_type:
        return
    LOGGER.info("VideoPhone {}".format(device.device_definition.get("label")))
    camera_config = ha_discovery_cameras(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
    )
    _publish_config(mqtt_client, camera_config)
    ringing_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="ringing",
    )
    _publish_config(mqtt_client, ringing_config)
    if ringing_config:
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=ringing_config.get("config", {}).get("state_topic"),
            payload={"ringing": "False"},
            retain=True,
        )
    for action in ["reboot", "halt", "open_latch", "open_gate"]:
        config = ha_discovery_devices(
            site_id=site_id,
            device=device,
            mqtt_config=mqtt_config,
            sensor_name=action,
        )
        _publish_and_subscribe(mqtt_client, config)
    device_config = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="snapshot",
    )
    _publish_and_subscribe(mqtt_client, device_config)
    stream = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="stream",
    )
    _publish_and_subscribe(mqtt_client, stream)
    if stream and stream.get("config", {}).get("command_topic"):
        _publish_stream_command_topics(mqtt_client, mqtt_config, site_id, device.id)
    video_backend = ha_discovery_devices(
        site_id=site_id,
        device=device,
        mqtt_config=mqtt_config,
        sensor_name="video_backend",
    )
    _publish_and_subscribe(mqtt_client, video_backend)
    if video_backend and video_backend.get("config", {}).get("command_topic"):
        _publish_snapshot_command_topics(mqtt_config, site_id, device.id)


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
            LOGGER.info("Configuring Device: {}".format(device.label))
            device_type = device.device_definition.get("type") or ""
            _configure_device_state_sensors(mqtt_client, mqtt_config, site_id, device)
            _configure_box_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_camera_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_remote_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_outdoor_siren(mqtt_client, mqtt_config, site_id, device)
            _configure_siren(mqtt_client, mqtt_config, site_id, device)
            _configure_motion_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_smoke_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_doorlock_device(mqtt_client, mqtt_config, site_id, device, device_type)
            _configure_videophone_device(mqtt_client, mqtt_config, site_id, device, device_type)


def update_sites_status(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    my_sites_id: list,
) -> None:
    """Update sites status (including history)."""
    LOGGER.info("Update Sites Status")
    for site_id in my_sites_id:
        try:
            site = api.get_site(site_id=site_id)
            LOGGER.info("Update {} Status".format(site.label))

            try:
                publish_site_state(mqtt_client, mqtt_config, site_id, site.security_level)
            except (OSError, ValueError) as e:
                LOGGER.warning("Error while updating MQTT: {}".format(e))
                continue
        except RemoteDisconnected:
            LOGGER.info("Retrying...")
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            LOGGER.warning("Error while refreshing site: {}".format(e))
            continue

        try:
            _publish_site_history(api, mqtt_client, mqtt_config, site_id)
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            LOGGER.warning("Error while getting site history: {}".format(e))
            continue


def _publish_site_history(
    api: SomfyProtectApi,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    site_id: str,
) -> None:
    events = api.get_history(site_id=site_id)
    for event in events:
        if not event:
            continue
        occurred_at = event.get("occurred_at")
        if not occurred_at:
            LOGGER.debug("Skipping history event with missing occurred_at")
            continue
        date_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        occurred_at_date = datetime.strptime(occurred_at, date_format)
        occurred_at_date = convert_utc_to_paris(date=occurred_at_date)
        paris_tz = pytz.timezone("Europe/Paris")
        now = datetime.now(paris_tz)
        message_vars = event.get("message_vars") or {}
        if now - occurred_at_date >= timedelta(seconds=3600):
            LOGGER.debug(
                "Event is too old {} {} {}".format(
                    event.get("message_key"),
                    message_vars.get("userDsp"),
                    message_vars.get("siteLabel"),
                )
            )
            continue
        if occurred_at in HISTORY:
            LOGGER.debug("History still published: {}".format(HISTORY[occurred_at]))
            continue
        payload = f"{event.get('message_key')}" f" {message_vars.get('userDsp')}" f" {message_vars.get('siteLabel')}"
        payload = payload.replace("None", "").strip().strip('"')
        payload = payload.replace(".", " ").title()
        HISTORY[occurred_at] = payload
        while len(HISTORY) > HISTORY_LIMIT:
            HISTORY.popitem(last=False)
        LOGGER.info("Publishing History: {}".format(HISTORY[occurred_at]))
        mqtt_publish(
            mqtt_client=mqtt_client,
            topic=f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/history",
            payload=payload,
            retain=True,
            is_json=False,
        )


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
                        topic=(
                            f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/"
                            f"{site_id}/{device.id}/video_backend"
                        ),
                        payload={"video_backend": video_backend},
                        retain=True,
                    )

                if "videophone" in device_type:
                    events = api.get_device_events(site_id=site_id, device_id=device.id)
                    if events:
                        for event in events:
                            event_id = event.get("event_id") or "unknown"
                            occurred_at = event.get("occurred_at") or "unknown"
                            clip_url = event.get("clip_cloudfront_url")
                            if clip_url:
                                LOGGER.info("Found a video: {}".format(clip_url))
                                write_to_media_folder(
                                    url=clip_url,
                                    site_id=site_id,
                                    device_id=device.id,
                                    label=device.device_definition.get("label") or device.id,
                                    event_id=event_id,
                                    occurred_at=occurred_at,
                                    media_type="video",
                                    mqtt_client=mqtt_client,
                                    mqtt_config=mqtt_config,
                                    dedupe_key=build_media_dedupe_key(
                                        media_type="video",
                                        site_id=site_id,
                                        device_id=device.id,
                                        url=clip_url,
                                        event_id=event_id,
                                        occurred_at=occurred_at,
                                    ),
                                )
                            snapshot_url = event.get("snapshot_cloudfront_url")
                            if snapshot_url:
                                LOGGER.info("Found a snapshot {}".format(snapshot_url))
                                write_to_media_folder(
                                    url=snapshot_url,
                                    site_id=site_id,
                                    device_id=device.id,
                                    label=device.device_definition.get("label") or device.id,
                                    event_id=event_id,
                                    occurred_at=occurred_at,
                                    media_type="snapshot",
                                    mqtt_client=mqtt_client,
                                    mqtt_config=mqtt_config,
                                    send_to_mqtt=True,
                                    dedupe_key=build_media_dedupe_key(
                                        media_type="snapshot",
                                        site_id=site_id,
                                        device_id=device.id,
                                        url=snapshot_url,
                                        event_id=event_id,
                                        occurred_at=occurred_at,
                                    ),
                                )

                settings = device.settings.get("global") or {}
                user_id = settings.get("user_id")
                if user_id:
                    DEVICE_TAG[user_id] = device.id
                publish_device_state(mqtt_client, mqtt_config, site_id, device)
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            LOGGER.warning("Error while refreshing devices: {}".format(e))
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
                    LOGGER.info("Shutter is {}".format(device.status.get("shutter_state", "opened")))
                    if device.status.get("shutter_state", "opened") != "closed":
                        api.camera_refresh_snapshot(site_id=site_id, device_id=device.id)
                        response = api.camera_snapshot(site_id=site_id, device_id=device.id)
                        if response and response.status_code == 200:
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

        except (requests.exceptions.RequestException, OSError, ValueError) as e:
            LOGGER.warning("Error while refreshing snapshot: {}".format(e))
            continue


def update_visiophone_snapshot(
    url: str,
    site_id: str,
    device_id: str,
    mqtt_client: MQTTClient,
    mqtt_config: dict,
    dedupe_key: str | None = None,
) -> None:
    """Download VisioPhone Snapshot"""
    LOGGER.info("Download VisioPhone Snapshot")
    if dedupe_key and has_processed_media(dedupe_key):
        LOGGER.info("Skipping already processed visiophone snapshot")
        return
    now = datetime.now()
    timestamp = int(now.timestamp())
    path = None

    try:
        response = HTTP_SESSION.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        path = f"{device_id}-{timestamp}.jpeg"
        with open(path, "wb") as tmp_file:
            for chunk in response.iter_content(1024):  # Lire en morceaux de 1 KB
                tmp_file.write(chunk)
    except requests.exceptions.RequestException as exc:
        LOGGER.warning("Error while Downloading snapshot: {}".format(exc))
        return

    if not path:
        LOGGER.warning("Snapshot file path not set")
        return

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
    if dedupe_key:
        mark_media_processed(dedupe_key)
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
    dedupe_key: str | None = None,
) -> None:
    """Download media to the local folder.

    Args:
        url (str): Media URL.
        site_id (str): Site ID.
        device_id (str): Device ID.
        label (str): Device label.
        event_id (str): Event ID.
        occurred_at (str): Event timestamp.
        media_type (str): Media type (video or snapshot).
        mqtt_client (MQTTClient): MQTT client instance.
        mqtt_config (dict): MQTT configuration.
        send_to_mqtt (bool): Whether to publish snapshots to MQTT.
    """
    LOGGER.info("Download VisioPhone Clip")
    directory = "/media/somfyprotect2mqtt"

    extention = None
    if media_type == "video":
        extention = "mp4"
    elif media_type == "snapshot":
        extention = "jpeg"
    else:
        LOGGER.warning("Unsupported media type: {}".format(media_type))
        return

    if dedupe_key and has_processed_media(dedupe_key):
        LOGGER.info("Skipping already processed visiophone {}".format(media_type))
        return

    try:
        os.makedirs(directory, exist_ok=True)

        response = HTTP_SESSION.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        path = f"{directory}/{label}-{occurred_at}-{event_id}.{extention}"

        with open(path, "wb") as file:
            for chunk in response.iter_content(1024):  # Lire en morceaux de 1 KB
                file.write(chunk)
        LOGGER.info("File wrote in {}".format(path))

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
        if dedupe_key:
            mark_media_processed(dedupe_key)
        LOGGER.info("Write Successful")

    except requests.exceptions.RequestException as exc:
        LOGGER.warning("Error while Downloading clip: {}".format(exc))
    except OSError as exc:
        LOGGER.warning("Unable to create directory {}: {}".format(directory, exc))
