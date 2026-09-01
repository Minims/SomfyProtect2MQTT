"""Tests for Home Assistant device MAC overrides."""

from business import _apply_device_mac_override
from somfy_protect.api.model import Device


def make_device(mac=None):
    """Build a badge for MAC override tests."""
    return Device(
        device_id="badge-id",
        site_id="site-id",
        label="Badge Alex",
        version="1.0.0",
        device_definition={"label": "Key Fob", "type": "remote"},
        status={},
        diagnosis={},
        settings={},
        mac=mac,
    )


def test_device_mac_override_uses_device_id_first():
    """Prefer the stable Somfy device ID over its editable label."""
    device = make_device()

    _apply_device_mac_override(
        device,
        {
            "device_macs": {
                "badge-id": "AA:BB:CC:DD:EE:FF",
                "Badge Alex": "11:22:33:44:55:66",
            }
        },
    )

    assert device.mac == "AA:BB:CC:DD:EE:FF"


def test_device_mac_override_accepts_unique_label():
    """Allow a unique Somfy label when the device ID is not readily available."""
    device = make_device()

    _apply_device_mac_override(device, {"device_macs": {"Badge Alex": " C4:A0:57:FD:5E:16 "}})

    assert device.mac == "C4:A0:57:FD:5E:16"


def test_device_mac_override_preserves_api_mac_without_match():
    """Keep an address returned by Somfy when no override matches."""
    device = make_device(mac="AA:BB:CC:DD:EE:FF")

    _apply_device_mac_override(device, {"device_macs": {"another-device": "11:22:33:44:55:66"}})

    assert device.mac == "AA:BB:CC:DD:EE:FF"
