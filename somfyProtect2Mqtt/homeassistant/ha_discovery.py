"""HomeAssistant MQTT Auto Discover"""

import logging
from ipaddress import ip_address

from homeassistant.capabilities import ALARM_STATUS as CAPABILITIES_ALARM_STATUS
from homeassistant.capabilities import DEVICE_CAPABILITIES
from somfy_protect.api.model import Device, Site

LOGGER = logging.getLogger(__name__)
ALARM_STATUS = CAPABILITIES_ALARM_STATUS
WIFI_DEVICE_TYPES = ("allinone", "box", "camera", "videophone")
BLUETOOTH_DEVICE_TYPES = ("remote",)


def _is_wifi_or_ip_field(field_name: object) -> bool:
    normalized_name = str(field_name).lower()
    return (
        any(marker in normalized_name for marker in ("wifi", "wi-fi", "wlan"))
        or normalized_name in {"ip", "ip_address", "ipv4", "ipv4_address", "ipv6", "ipv6_address", "ssid"}
        or normalized_name.startswith("ip_")
        or normalized_name.endswith(("_ip", "_ssid"))
    )


def _contains_wifi_or_ip(value: object) -> bool:
    if isinstance(value, dict):
        for field_name, field_value in value.items():
            if _is_wifi_or_ip_field(field_name) and field_value is not None and field_value != "":
                return True
            if _contains_wifi_or_ip(field_value):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_wifi_or_ip(item) for item in value)
    if isinstance(value, str):
        try:
            ip_address(value)
        except ValueError:
            return False
        return True
    return False


def _device_connection_type(device: Device) -> str:
    device_type = str(device.device_definition.get("type") or "").lower()
    if any(wifi_type in device_type for wifi_type in WIFI_DEVICE_TYPES):
        return "mac"
    if any(bluetooth_type in device_type for bluetooth_type in BLUETOOTH_DEVICE_TYPES):
        return "bluetooth"
    if any(_contains_wifi_or_ip(data) for data in (device.status, device.settings, device.device_definition)):
        return "mac"
    return "bluetooth"


def _device_connections(device: Device) -> list[list[str]]:
    if not device.mac:
        return []
    return [[_device_connection_type(device), device.mac]]


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
    if isinstance(code, (int, str)) and not isinstance(code, bool):
        code = str(code)
        if code not in ("", "0"):
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
    capability = DEVICE_CAPABILITIES.get(sensor_name)
    if capability is None:
        LOGGER.warning(f"Unknown capability {sensor_name} for device {device.label} ({device.id}), skipping discovery")
        return None

    device_type = capability.get("type")
    capability_config = capability.get("config", {})

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
    connections = _device_connections(device)
    if connections:
        device_info["connections"] = connections

    command_topic = (
        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/{sensor_name}/command"
    )
    device_config["topic"] = (
        f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/"
        f"{device_type}/{site_id}_{device.id}/{sensor_name}/config"
    )
    device_config["config"] = {
        "name": sensor_name,
        "unique_id": f"{device.id}_{sensor_name}",
        "state_topic": (f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state"),
        "value_template": "{{ value_json." + sensor_name + " }}",
        "device": device_info,
    }

    for config_entry, config_value in capability_config.items():
        device_config["config"][config_entry] = config_value
        # Specifiy for Intellitag Sensivity
        if device.device_definition.get("label") == "IntelliTag" and sensor_name == "sensitivity":
            intellitag_capability = DEVICE_CAPABILITIES.get(f"{sensor_name}_{device.device_definition.get('label')}")
            if intellitag_capability:
                device_config["config"][config_entry] = intellitag_capability.get("config", {}).get(config_entry)
    if device_type in ("switch", "number", "select", "button"):
        device_config["config"]["command_topic"] = command_topic
    if device_type == "button":
        device_config["config"].pop("state_topic", None)
        device_config["config"].pop("value_template", None)
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
    connections = _device_connections(device)
    if connections:
        device_info["connections"] = connections

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
