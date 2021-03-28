from somfy_protect_api.api.model import Site, Device
from somfy_protect_api.api.devices.category import Category

DEVICE_CAPABILITIES = {
    "temperature": {
        "type": "sensor",
        "config": {"device_class": "temperature", "unit_of_measurement": "°C",},
    },
    "battery_level": {
        "type": "sensor",
        "config": {"device_class": "voltage", "unit_of_measurement": "V",},
    },
    "battery_low": {"type": "binary_sensor", "config": {"device_class": "battery",},},
    "rlink_quality": {
        "type": "sensor",
        "config": {"device_class": "signal_strength", "unit_of_measurement": "dB",},
    },
    "rlink_quality_percent": {
        "type": "sensor",
        "config": {"device_class": "signal_strength", "unit_of_measurement": "%",},
    },
    "recalibration_required": {
        "type": "binary_sensor",
        "config": {"device_class": "problem",},
    },
    "cover_present": {
        "type": "binary_sensor",
        "config": {"pl_on": "True", "pl_off": "False",},
    },
    "shutter_state": {
        "type": "switch",
        "config": {"pl_on": "opened", "pl_off": "closed",},
    },
}


def ha_discovery_alarm(site: Site, mqtt_config: dict):
    site_config = {}
    site_config[
        "topic"
    ] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/alarm_control_panel/{site.id}/config"
    site_config["config"] = {
        "name": site.label,
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/state",
        "command_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/command",
        "payload_arm_away": "armed",
        "payload_arm_night": "partial",
        "payload_disarm": "disarmed",
    }
    return site_config


def ha_discovery_devices(
    site_id: str, device: Device, mqtt_config: dict, sensor_name: str,
):
    device_config = {}
    device_type = DEVICE_CAPABILITIES.get(sensor_name).get("type")
    device_config[
        "topic"
    ] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/{device_type}/{site_id}/{device.id}_{sensor_name}/config"
    device_config["config"] = {
        "name": f"{device.label} {sensor_name}",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
        "value_template": "{{ value_json." + sensor_name + " }}",
    }

    for config_entry in DEVICE_CAPABILITIES.get(sensor_name).get("config"):
        device_config["config"][config_entry] = (
            DEVICE_CAPABILITIES.get(sensor_name).get("config").get(config_entry)
        )
    if device_type == "switch":
        device_config["config"][
            "command_topic"
        ] = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/command"
    return device_config
