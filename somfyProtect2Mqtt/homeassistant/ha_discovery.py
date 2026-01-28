"""HomeAssistant MQTT Auto Discover"""

import logging
from somfy_protect.api.model import Site, Device
from homeassistant.capabilities import ALARM_STATUS, DEVICE_CAPABILITIES

LOGGER = logging.getLogger(__name__)


def ha_discovery_alarm(site: Site, mqtt_config: dict, homeassistant_config: dict):
    """Auto Discover Alarm"""
    if homeassistant_config:
        code = homeassistant_config.get("code")
        code_arm_required = homeassistant_config.get("code_arm_required")
        code_disarm_required = homeassistant_config.get("code_disarm_required")
    else:
        code = None
        code_arm_required = None
        code_disarm_required = None

    site_config = {}

    site_info = {
        "identifiers": [site.id],
        "manufacturer": "Somfy",
        "model": "Somfy Home Alarm",
        "name": "Somfy Home Alarm",
        "sw_version": "SomfyProtect2MQTT",
    }

    command_topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/command"
    site_config["topic"] = (
        f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/alarm_control_panel/{site.id}/alarm/config"
    )
    site_config["config"] = {
        "name": site.label,
        "unique_id": f"{site.id}_{site.label}",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/state",
        "command_topic": command_topic,
        "payload_arm_away": "armed",
        "payload_arm_night": "partial",
        "payload_disarm": "disarmed",
        "value_template": "{{ value_json.security_level }}",
        "supported_features": ["arm_night", "arm_away", "trigger"],
        "device": site_info,
    }
    if code and (isinstance(code, int)):
        site_config["config"]["code"] = code
    if not code_arm_required:
        site_config["config"]["code_arm_required"] = False
    if not code_disarm_required:
        site_config["config"]["code_disarm_required"] = False
    return site_config


def ha_discovery_history(site: Site, mqtt_config: dict):
    """Auto Discover History"""
    site_config = {}

    site_info = {
        "identifiers": [site.id],
        "manufacturer": "Somfy",
        "model": "Somfy Home Alarm",
        "name": "Somfy Home Alarm",
        "sw_version": "SomfyProtect2MQTT",
    }

    site_config["topic"] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/text/{site.id}/history/config"
    site_config["config"] = {
        "name": f"{site.label}_history",
        "unique_id": f"{site.id}_{site.label}_history",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/history",
        "device": site_info,
        "mode": "text",
        "command_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/history",
        "min": 0,
        "max": 255,
    }
    return site_config


def ha_discovery_alarm_actions(site: Site, mqtt_config: dict):
    """Auto Discover Actions"""
    site_config = {}

    site_info = {
        "identifiers": [site.id],
        "manufacturer": "Somfy",
        "model": "Somfy Home Alarm",
        "name": "Somfy Home Alarm",
        "sw_version": "SomfyProtect2MQTT",
    }

    command_topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/siren/command"
    site_config["topic"] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/switch/{site.id}/siren/config"
    site_config["config"] = {
        "name": "Siren",
        "unique_id": f"{site.id}_{site.label}",
        "command_topic": command_topic,
        "device": site_info,
        "pl_on": "panic",
        "pl_off": "stop",
    }

    return site_config


def ha_discovery_devices(
    site_id: str,
    device: Device,
    mqtt_config: dict,
    sensor_name: str,
):
    """Auto Discover Devices"""
    device_config = {}
    device_type = DEVICE_CAPABILITIES.get(sensor_name).get("type")

    update_available = device.update_available
    if update_available is False:
        update_available = "(Up to Date)"
    else:
        update_available = f"(New Version Available: {update_available})"

    device_info = {
        "identifiers": [device.id],
        "manufacturer": "Somfy",
        "model": device.device_definition.get("label"),
        "name": device.label,
        "sw_version": f"{device.version} {update_available}",
    }

    command_topic = (
        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/{sensor_name}/command"
    )
    device_config["topic"] = (
        f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/{device_type}/{site_id}_{device.id}/{sensor_name}/config"
    )
    device_config["config"] = {
        "name": sensor_name,
        "unique_id": f"{device.id}_{sensor_name}",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
        "value_template": "{{ value_json." + sensor_name + " }}",
        "device": device_info,
    }

    for config_entry in DEVICE_CAPABILITIES.get(sensor_name).get("config"):
        device_config["config"][config_entry] = DEVICE_CAPABILITIES.get(sensor_name).get("config").get(config_entry)
        # Specifiy for Intellitag Sensivity
        if device.device_definition.get("label") == "IntelliTag" and sensor_name == "sensitivity":
            device_config["config"][config_entry] = (
                DEVICE_CAPABILITIES.get(f"{sensor_name}_{device.device_definition.get('label')}")
                .get("config")
                .get(config_entry)
            )
    if device_type in ("switch", "number", "select", "button"):
        device_config["config"]["command_topic"] = command_topic
    if sensor_name == "snapshot":
        device_config["config"].pop("value_template")
    if sensor_name == "stream":
        device_config["config"].pop("value_template")
    if sensor_name == "presence":
        device_config["config"][
            "state_topic"
        ] = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/presence"
    if sensor_name == "motion_sensor":
        device_config["config"][
            "state_topic"
        ] = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/pir"
        if device.device_definition.get("label") == "IntelliTag":
            device_config["config"]["device_class"] = "safety"
        if device.device_definition.get("label") == "Myfox Security Infrared Sensor":
            device_config["config"]["device_class"] = "motion"
    if sensor_name == "ringing":
        device_config["config"][
            "state_topic"
        ] = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/ringing"
    if sensor_name == "video_backend":
        device_config["config"][
            "state_topic"
        ] = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/video_backend"

    return device_config


def ha_discovery_cameras(
    site_id: str,
    device: Device,
    mqtt_config: dict,
):
    """Auto Discover Cameras"""
    camera_config = {}

    device_info = {
        "identifiers": [device.id],
        "manufacturer": "Somfy",
        "model": device.device_definition.get("label"),
        "name": device.label,
        "sw_version": device.version,
    }

    camera_config["topic"] = (
        f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/camera/{site_id}_{device.id}/snapshot/config"
    )
    camera_config["config"] = {
        "name": "snapshot",
        "unique_id": f"{device.id}_snapshot",
        "topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/snapshot",
        "device": device_info,
    }

    return camera_config
