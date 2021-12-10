from somfy_protect_api.api.model import Site, Device
from somfy_protect_api.api.devices.category import Category

ALARM_STATUS = {
    "partial": "armed_night",
    "disarmed": "disarmed",
    "armed": "armed_away",
    "triggered": "triggered",  # To Check Status is currently unknown
}

# NOT USED, JUST FOR INFO
# DEVICE_SETTINGS = {
#     "IntelliTag": {
#         "global": {
#             "sensitivity": "[1-9]",
#             "support_type": ["slidewindow", "slidedoor", "externdoor", "window"],
#             "night_mode_enabled": [True, False],
#             "prealarm_enabled": [True, False],
#         },
#     },
#     "Myfox Security Infrared Sensor": {
#         "global": {
#             "sensitivity_level": ["low", "medium", "high"],
#             "light_enabled": True,
#             "auto_protect_enabled": True,
#             "night_mode_enabled": False,
#             "prealarm_enabled": True,
#         },
#         "disarmed": {"auto_protect_enabled": [True, False]},
#         "partial": {"auto_protect_enabled": [True, False]},
#         "armed": {"auto_protect_enabled": [True, False]},
#     },
#     "Key Fob": {"global": {"enabled": [True, False],},},
#     "Somfy Indoor Camera": {
#         "global": {
#             "detection_enabled": [True, False],
#             "video_mode": '["SD","HD"]',
#             "sensitivity": "[0-100]",
#             "night_vision": ["manual", "automatic"],
#             "night_mode": "[0-2]",
#             "led_enabled": [True, False],
#             "night_mode_enabled": [True, False],
#             "sound_recording_enabled": [True, False],
#             "sound_enabled": [True, False],
#             "siren_on_camera_detection_disabled": [True, False],
#             "hdr_enabled": [True, False],
#             "prealarm_enabled": [True, False],
#         }
#     },
#     "Myfox Security Outdoor Siren": {
#         "global": {
#             "light_enabled": [True, False],
#             "sound_enabled": [True, False],
#             "auto_protect_enabled": [True, False],
#         },
#         "disarmed": {"auto_protect_enabled": [True, False]},
#         "partial": {"auto_protect_enabled": [True, False]},
#         "armed": {"auto_protect_enabled": [True, False]},
#     },
#     "Myfox Security Siren": {
#         "global": {
#             "light_enabled": [True, False],
#             "sound_enabled": [True, False],
#             "auto_protect_enabled": [True, False],
#         },
#         "disarmed": {"auto_protect_enabled": [True, False]},
#         "partial": {"auto_protect_enabled": [True, False]},
#         "armed": {"auto_protect_enabled": [True, False]},
#     },
# }

DEVICE_CAPABILITIES = {
    "temperature": {
        "type": "sensor",
        "config": {
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "battery_level": {
        "type": "sensor",
        "config": {
            "device_class": "battery",
            "unit_of_measurement": "%",
        },
    },
    "battery_low": {
        "type": "binary_sensor",
        "config": {
            "device_class": "battery",
        },
    },
    "rlink_quality": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "dB",
        },
    },
    "rlink_quality_percent": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "%",
        },
    },
    "wifi_level": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "dB",
        },
    },
    "wifi_level_percent": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "%",
        },
    },
    "lora_quality_percent": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "%",
        },
    },
    "mfa_quality_percent": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "%",
        },
    },
    "recalibration_required": {
        "type": "binary_sensor",
        "config": {
            "device_class": "problem",
        },
    },
    "cover_present": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "device_lost": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "shutter_state": {
        "type": "switch",
        "config": {
            "pl_on": "opened",
            "pl_off": "closed",
        },
    },
    "sound_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "light_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "auto_protect_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "night_mode_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "prealarm_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "sp_smoke_detector_alarm_muted": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "sp_smoke_detector_error_chamber": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "sp_smoke_detector_no_disturb": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "sp_smoke_detector_role": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "end_device",
            "pl_off": "coordinator",
        },
    },
    "sp_smoke_detector_smoke_detection": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "snapshot": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
            "optimistic": "True",
        },
    },
}


def ha_discovery_alarm(site: Site, mqtt_config: dict, homeassistant_config: dict):

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
        "name": site.label,
        "sw_version": "SomfyProtect2MQTT: Alpha",
    }

    command_topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/command"
    site_config[
        "topic"
    ] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/alarm_control_panel/{site.id}/alarm/config"
    site_config["config"] = {
        "name": site.label,
        "unique_id": f"{site.id}_{site.label}",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/state",
        "command_topic": command_topic,
        "payload_arm_away": "armed",
        "payload_arm_night": "partial",
        "payload_disarm": "disarmed",
        "value_template": "{{ value_json.security_level }}",
        "device": site_info,
    }
    if code and (isinstance(code, int)):
        site_config["config"]["code"] = code
    if not code_arm_required:
        site_config["config"]["code_arm_required"] = False
    if not code_disarm_required:
        site_config["config"]["code_disarm_required"] = False
    return site_config


def ha_discovery_alarm_actions(site: Site, mqtt_config: dict):
    site_config = {}

    site_info = {
        "identifiers": [site.id],
        "manufacturer": "Somfy",
        "model": "Somfy Home Alarm",
        "name": site.label,
        "sw_version": "SomfyProtect2MQTT: Alpha",
    }

    command_topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site.id}/siren/command"
    site_config["topic"] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/switch/{site.id}/siren/config"
    site_config["config"] = {
        "name": f"{site.label} Siren",
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
    device_config = {}
    device_type = DEVICE_CAPABILITIES.get(sensor_name).get("type")

    device_info = {
        "identifiers": [device.id],
        "manufacturer": "Somfy",
        "model": device.device_definition.get("label"),
        "name": device.label,
        "sw_version": device.version,
    }

    command_topic = (
        f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/{sensor_name}/command"
    )
    device_config[
        "topic"
    ] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/{device_type}/{site_id}_{device.id}/{sensor_name}/config"
    device_config["config"] = {
        "name": f"{device.label} {sensor_name}",
        "unique_id": f"{device.id}_{sensor_name}",
        "state_topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
        "value_template": "{{ value_json." + sensor_name + " }}",
        "device": device_info,
    }

    for config_entry in DEVICE_CAPABILITIES.get(sensor_name).get("config"):
        device_config["config"][config_entry] = DEVICE_CAPABILITIES.get(sensor_name).get("config").get(config_entry)
    if device_type == "switch":
        device_config["config"]["command_topic"] = command_topic
    if sensor_name == "snapshot":
        device_config["config"].pop("value_template")

    return device_config


def ha_discovery_cameras(
    site_id: str,
    device: Device,
    mqtt_config: dict,
):
    camera_config = {}

    device_info = {
        "identifiers": [device.id],
        "manufacturer": "Somfy",
        "model": device.device_definition.get("label"),
        "name": device.label,
        "sw_version": device.version,
    }

    camera_config[
        "topic"
    ] = f"{mqtt_config.get('ha_discover_prefix', 'homeassistant')}/camera/{site_id}_{device.id}/snapshot/config"
    camera_config["config"] = {
        "name": f"{device.label} snapshot",
        "unique_id": f"{device.id}_snapshot",
        "topic": f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/snapshot",
        "device": device_info,
    }

    return camera_config
