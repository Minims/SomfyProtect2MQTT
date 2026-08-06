"""Tests for Home Assistant MQTT discovery."""

from types import SimpleNamespace

import pytest
from homeassistant.ha_discovery import ha_discovery_alarm


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
