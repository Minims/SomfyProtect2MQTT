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


def make_device(mac=None, device_type="camera", status=None, settings=None):
    """Build a device for discovery tests."""
    return Device(
        device_id="device-id",
        site_id="site-id",
        label="Camera",
        version="1.0.0",
        device_definition={"label": "Somfy Device", "type": device_type},
        status=status or {},
        diagnosis={},
        settings=settings or {},
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
@pytest.mark.parametrize(
    ("device_type", "status", "settings", "expected_connection_type"),
    [
        ("box", {}, {}, "mac"),
        ("camera", {}, {}, "mac"),
        ("allinone", {}, {}, "mac"),
        ("videophone", {}, {}, "mac"),
        ("remote", {"wifi_level_percent": 100}, {}, "bluetooth"),
        ("unknown", {"ip_address": "192.0.2.1"}, {}, "mac"),
        ("unknown", {"address": "2001:db8::1"}, {}, "mac"),
        ("unknown", {}, {"global": {"wifi_ssid": "Home"}}, "mac"),
        ("tag", {}, {}, "bluetooth"),
    ],
)
def test_device_discovery_exposes_connection_by_transport(
    discovery, device_type, status, settings, expected_connection_type
):
    """Expose Wi-Fi and Bluetooth addresses with their Home Assistant connection type."""
    device = make_device(
        mac="AA:BB:CC:DD:EE:FF",
        device_type=device_type,
        status=status,
        settings=settings,
    )
    mqtt_config = {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"}

    if discovery is ha_discovery_devices:
        result = discovery("site-id", device, mqtt_config, "battery_level")
    else:
        result = discovery("site-id", device, mqtt_config)

    assert result["config"]["device"]["connections"] == [[expected_connection_type, "AA:BB:CC:DD:EE:FF"]]


@pytest.mark.parametrize("discovery", [ha_discovery_devices, ha_discovery_cameras])
@pytest.mark.parametrize("mac", ["aabbccddeeff", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff"])
def test_device_discovery_formats_bluetooth_mac(discovery, mac):
    """Format Bluetooth addresses so Home Assistant can link matching devices."""
    device = make_device(mac=mac, device_type="remote")
    mqtt_config = {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"}

    if discovery is ha_discovery_devices:
        result = discovery("site-id", device, mqtt_config, "battery_level")
    else:
        result = discovery("site-id", device, mqtt_config)

    assert result["config"]["device"]["connections"] == [["bluetooth", "AA:BB:CC:DD:EE:FF"]]


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
