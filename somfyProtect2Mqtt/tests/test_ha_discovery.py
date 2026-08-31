"""Tests for Home Assistant MQTT discovery."""

from types import SimpleNamespace

import pytest
from homeassistant.ha_discovery import ha_discovery_alarm, ha_discovery_cameras, ha_discovery_devices
from somfy_protect.api.model import Device


@pytest.fixture
def site():
    """Return the site attributes used by alarm discovery."""
    return SimpleNamespace(id="site-id", label="Home")


def alarm_config(site, code):
    """Build the alarm discovery configuration for a code value."""
    return ha_discovery_alarm(
        site,
        {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"},
        {
            "code": code,
            "code_arm_required": True,
            "code_disarm_required": True,
        },
    )["config"]


def make_device(mac=None):
    """Build a device for discovery tests."""
    return Device(
        device_id="device-id",
        site_id="site-id",
        label="Camera",
        version="1.0.0",
        device_definition={"label": "Somfy Camera"},
        status={},
        diagnosis={},
        settings={},
        mac=mac,
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (1234, "1234"),
        ("1234", "1234"),
        ("0123", "0123"),
        ("0000", "0000"),
    ],
)
def test_alarm_discovery_preserves_supported_codes(site, code, expected):
    """Publish supported codes as strings without losing leading zeroes."""
    assert alarm_config(site, code)["code"] == expected


@pytest.mark.parametrize("code", [None, "", 0, "0", True, False, 12.3, []])
def test_alarm_discovery_ignores_disabled_or_invalid_codes(site, code):
    """Do not publish disabled or invalid code values."""
    assert "code" not in alarm_config(site, code)


@pytest.mark.parametrize("discovery", [ha_discovery_devices, ha_discovery_cameras])
def test_device_discovery_exposes_mac_connection(discovery):
    """Expose a Wi-Fi or BLE MAC address on the Home Assistant device."""
    device = make_device(mac="AA:BB:CC:DD:EE:FF")
    mqtt_config = {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"}

    if discovery is ha_discovery_devices:
        result = discovery("site-id", device, mqtt_config, "battery_level")
    else:
        result = discovery("site-id", device, mqtt_config)

    assert result["config"]["device"]["connections"] == [["mac", "AA:BB:CC:DD:EE:FF"]]


@pytest.mark.parametrize("discovery", [ha_discovery_devices, ha_discovery_cameras])
def test_device_discovery_omits_missing_mac_connection(discovery):
    """Do not publish an empty Home Assistant device connection."""
    device = make_device()
    mqtt_config = {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"}

    if discovery is ha_discovery_devices:
        result = discovery("site-id", device, mqtt_config, "battery_level")
    else:
        result = discovery("site-id", device, mqtt_config)

    assert "connections" not in result["config"]["device"]
