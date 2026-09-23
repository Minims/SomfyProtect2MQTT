"""Tests for the site history published over MQTT."""

from types import SimpleNamespace

from business import _history_attributes
from homeassistant.ha_discovery import ha_discovery_history


def test_history_discovery_exposes_attributes_topic():
    """Let Home Assistant read the history event details as attributes."""
    config = ha_discovery_history(
        SimpleNamespace(id="site-id", label="Home"),
        {"topic_prefix": "somfyProtect2mqtt", "ha_discover_prefix": "homeassistant"},
    )["config"]

    assert config["json_attributes_topic"] == "somfyProtect2mqtt/site-id/history/attributes"


def test_history_attributes_identify_the_key_fob():
    """Report which key fob changed the security level."""
    event = {
        "occurred_at": "2026-01-01T10:00:00.000000Z",
        "message_type": "security_level",
        "message_key": "site.securityLevel.disarmed.userRemote",
        "message_vars": {"deviceLabel": "Badge Alice", "userDsp": "Alice"},
        "origin": {"type": "user_device", "user_id": "user-id", "device_id": "fob-id"},
    }

    assert _history_attributes(event) == {
        "occurred_at": "2026-01-01T10:00:00.000000Z",
        "message_type": "security_level",
        "message_key": "site.securityLevel.disarmed.userRemote",
        "origin_type": "user_device",
        "user": "Alice",
        "user_id": "user-id",
        "device": "Badge Alice",
        "device_id": "fob-id",
    }


def test_history_attributes_identify_the_mobile_user():
    """Report which user changed the security level from the mobile app."""
    event = {
        "occurred_at": "2026-01-01T10:00:00.000000Z",
        "message_type": "security_level",
        "message_key": "site.securityLevel.disarmed.userMobile",
        "message_vars": {"userDsp": "Bob"},
        "origin": {"type": "user", "user_id": "user-id"},
    }

    attributes = _history_attributes(event)

    assert attributes["user"] == "Bob"
    assert attributes["user_id"] == "user-id"
    assert attributes["device"] is None
    assert attributes["device_id"] is None


def test_history_attributes_tolerate_missing_fields():
    """Do not fail on events without message variables or origin."""
    assert _history_attributes({"occurred_at": "2026-01-01T10:00:00.000000Z"})["user"] is None
