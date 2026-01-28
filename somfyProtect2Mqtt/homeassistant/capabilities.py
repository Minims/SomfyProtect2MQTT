"""Home Assistant Device Capabilities Definitions.

This module contains the DEVICE_CAPABILITIES dictionary that maps
Somfy Protect device properties to Home Assistant entity configurations.

Each capability defines:
- type: The Home Assistant entity type (sensor, binary_sensor, switch, etc.)
- config: Entity-specific configuration options
"""

# Mapping of Somfy Protect security levels to Home Assistant alarm states
ALARM_STATUS = {
    "partial": "armed_night",
    "disarmed": "disarmed",
    "armed": "armed_away",
    "triggered": "triggered",
}

# Device capabilities mapping for Home Assistant MQTT Discovery
DEVICE_CAPABILITIES = {
    # ==========================================================================
    # Temperature and Battery Sensors
    # ==========================================================================
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
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    # ==========================================================================
    # Signal Strength Sensors
    # ==========================================================================
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
            "unit_of_measurement": "%",
        },
    },
    "fsk_level": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "dB",
        },
    },
    "ble_level": {
        "type": "sensor",
        "config": {
            "device_class": "signal_strength",
            "unit_of_measurement": "dB",
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
            "unit_of_measurement": "%",
        },
    },
    "lora_quality_percent": {
        "type": "sensor",
        "config": {
            "unit_of_measurement": "%",
        },
    },
    "mfa_quality_percent": {
        "type": "sensor",
        "config": {
            "unit_of_measurement": "%",
        },
    },
    # ==========================================================================
    # Configurable Numbers (Sensitivity, Thresholds, etc.)
    # ==========================================================================
    "sensitivity": {
        "type": "number",
        "config": {"min": 0, "max": 100},
    },
    "ambient_light_threshold": {
        "type": "number",
        "config": {"min": 0, "max": 255},
    },
    "lighting_duration": {
        "type": "number",
        "config": {"min": 0, "max": 900},
    },
    "sensitivity_IntelliTag": {
        "type": "number",
        "config": {"min": 1, "max": 9},
    },
    # ==========================================================================
    # Select Options (Dropdowns)
    # ==========================================================================
    "night_vision": {
        "type": "select",
        "config": {
            "options": ["automatic", "on", "off"],
        },
    },
    "sensitivity_level": {
        "type": "select",
        "config": {
            "options": ["low", "medium", "high"],
        },
    },
    "support_type": {
        "type": "select",
        "config": {
            "options": [
                "slidedoor",
                "window",
                "externdoor",
                "interndoor",
                "slidewindow",
                "garage",
            ],
        },
    },
    "video_mode": {
        "type": "select",
        "config": {
            "options": ["FHD", "HD", "SD"],
        },
    },
    "smart_alarm_duration": {
        "type": "select",
        "config": {
            "options": ["30", "60", "90", "120"],
        },
    },
    "lighting_trigger": {
        "type": "select",
        "config": {
            "options": ["manual", "always"],
        },
    },
    "video_backend": {
        "type": "select",
        "config": {
            "options": ["evostream", "webrtc"],
        },
    },
    # ==========================================================================
    # Status Sensors (Generic)
    # ==========================================================================
    "power_mode": {
        "type": "sensor",
        "config": {},
    },
    "wifi_ssid": {
        "type": "sensor",
        "config": {},
    },
    "temperatureAt": {
        "type": "sensor",
        "config": {},
    },
    "last_online_at": {
        "type": "sensor",
        "config": {},
    },
    "last_offline_at": {
        "type": "sensor",
        "config": {},
    },
    "mounted_at": {
        "type": "sensor",
        "config": {},
    },
    "last_shutter_closed_at": {
        "type": "sensor",
        "config": {},
    },
    "last_shutter_opened_at": {
        "type": "sensor",
        "config": {},
    },
    "last_status_at": {
        "type": "sensor",
        "config": {},
    },
    "model": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_test_at": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_test_success_at": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_online_at": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_offline_at": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_connected_at": {
        "type": "sensor",
        "config": {},
    },
    "mfa_last_disconnected_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_test_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_test_success_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_online_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_test_on_going": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_offline_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_connected_at": {
        "type": "sensor",
        "config": {},
    },
    "lora_last_disconnected_at": {
        "type": "sensor",
        "config": {},
    },
    "last_check_in_state": {
        "type": "sensor",
        "config": {},
    },
    "last_check_out_state": {
        "type": "sensor",
        "config": {},
    },
    "keep_alive": {
        "type": "sensor",
        "config": {},
    },
    "rlink_state": {
        "type": "sensor",
        "config": {},
    },
    "battery_level_state": {
        "type": "sensor",
        "config": {},
    },
    "power_state": {
        "type": "sensor",
        "config": {},
    },
    "thresholdAcc": {
        "type": "sensor",
        "config": {},
    },
    "gsm_antenna_in_use": {
        "type": "sensor",
        "config": {},
    },
    "night_mode": {
        "type": "sensor",
        "config": {},
    },
    "door_lock_state": {
        "type": "sensor",
        "config": {},
    },
    "gateway_id": {
        "type": "sensor",
        "config": {},
    },
    "auto_lock": {
        "type": "sensor",
        "config": {},
    },
    # ==========================================================================
    # Binary Sensors (On/Off States)
    # ==========================================================================
    "recalibration_required": {
        "type": "binary_sensor",
        "config": {
            "device_class": "problem",
            "pl_on": "True",
            "pl_off": "False",
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
        "type": "device_tracker",
        "config": {
            "payload_home": "False",
            "payload_not_home": "True",
        },
    },
    "push_to_talk_available": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "homekit_capable": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "smoke": {
        "type": "binary_sensor",
        "device_class": "smoke",
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
    "recalibrateable": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "is_full_gsm": {
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
    "motion_sensor": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "ringing": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "door_state": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "open",
            "pl_off": "closed",
        },
    },
    "is_sensor_tof_activated": {
        "type": "binary_sensor",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    # ==========================================================================
    # Switches (Controllable On/Off)
    # ==========================================================================
    "latch_wired": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "gate_wired": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "lighting_state": {
        "type": "switch",
        "config": {
            "state_on": "True",
            "state_off": "False",
            "pl_on": "light_on",
            "pl_off": "light_off",
        },
    },
    "open_door": {
        "type": "switch",
        "config": {
            "state_on": "locked",
            "state_off": "unlocked",
            "pl_on": "lock",
            "pl_off": "unlock",
            "optimistic": "True",
        },
    },
    "gate": {
        "type": "switch",
        "config": {
            "pl_on": "gate_open",
            "pl_off": "gate_close",
            "optimistic": "True",
        },
    },
    "garage": {
        "type": "switch",
        "config": {
            "pl_on": "garage_open",
            "pl_off": "garage_close",
            "optimistic": "True",
        },
    },
    "rolling_shutter": {
        "type": "switch",
        "config": {
            "pl_on": "rolling_shutter_up",
            "pl_off": "rolling_shutter_down",
            "optimistic": "True",
        },
    },
    "shutter_state": {
        "type": "switch",
        "config": {
            "state_on": "opened",
            "state_off": "closed",
            "pl_on": "shutter_open",
            "pl_off": "shutter_close",
            "icon": "mdi:window-shutter",
        },
    },
    "detection_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "led_enabled": {
        "type": "switch",
        "config": {"pl_on": "True", "pl_off": "False", "icon": "mdi:led-on"},
    },
    "hdr_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "lighting_wired": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "siren_disabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "siren_on_camera_detection_disabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "auto_rotate_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "sound_recording_enabled": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
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
    "code_required_to_arm": {
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
    "snapshot": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
            "optimistic": "True",
        },
    },
    "stream": {
        "type": "switch",
        "config": {
            "pl_on": "stream_start",
            "pl_off": "stream_stop",
            "optimistic": "True",
        },
    },
    "direct_lock": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "silent_mode": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "open_door_alarm": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "lock_pick_alarm": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "breaking_alarm": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    "is_manual_alarm": {
        "type": "switch",
        "config": {
            "pl_on": "True",
            "pl_off": "False",
        },
    },
    # ==========================================================================
    # Buttons (Actions)
    # ==========================================================================
    "open_latch": {
        "type": "button",
        "config": {"payload_press": "latch"},
    },
    "open_gate": {
        "type": "button",
        "config": {"payload_press": "gate"},
    },
    "door_force_lock": {
        "type": "button",
        "config": {"payload_press": "force_lock"},
    },
    "reboot": {
        "type": "button",
        "config": {"payload_press": "reboot", "icon": "mdi:restart"},
    },
    "halt": {
        "type": "button",
        "config": {"payload_press": "halt", "icon": "mdi:stop-circle"},
    },
    "test_smokeExtended": {
        "type": "button",
        "config": {"payload_press": "test_smokeExtended"},
    },
    "test_siren1s": {
        "type": "button",
        "config": {"payload_press": "test_siren1s"},
    },
    "test_armed": {
        "type": "button",
        "config": {"payload_press": "test_armed"},
    },
    "test_disarmed": {
        "type": "button",
        "config": {"payload_press": "test_disarmed"},
    },
    "test_intrusion": {
        "type": "button",
        "config": {"payload_press": "test_intrusion"},
    },
    "test_ok": {
        "type": "button",
        "config": {"payload_press": "test_ok"},
    },
    # ==========================================================================
    # Device Trackers (Presence)
    # ==========================================================================
    "presence": {
        "type": "device_tracker",
        "config": {
            "payload_home": "home",
            "payload_not_home": "not_home",
        },
    },
}
