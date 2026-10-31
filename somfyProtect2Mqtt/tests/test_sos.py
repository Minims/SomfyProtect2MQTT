"""Tests for the SOS button and alarm commands."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from business import ha_sites_config
from business import mqtt as mqtt_business
from requests import Response
from somfy_protect.api import SomfyProtectApi


@pytest.mark.parametrize(
    ("mqtt_config", "topic_prefix", "discovery_prefix"),
    [
        ({}, "somfyProtect2mqtt", "homeassistant"),
        ({"topic_prefix": "protect", "ha_discover_prefix": "ha"}, "protect", "ha"),
    ],
)
def test_discovered_sos_button_sends_silent_panic(monkeypatch, mqtt_config, topic_prefix, discovery_prefix):
    """Publish a usable site button whose press sends a silent panic request."""
    monkeypatch.setattr(mqtt_business, "SUBSCRIBE_TOPICS", set())
    api = Mock(spec=SomfyProtectApi)
    api.get_site.return_value = SimpleNamespace(id="site-id", label="Home")
    mqtt_client = SimpleNamespace(client=Mock())

    ha_sites_config(api, mqtt_client, mqtt_config, {}, ["site-id"])

    published = {call.args[0]: call for call in mqtt_client.client.publish.call_args_list}
    discovery_topic = f"{discovery_prefix}/button/site-id/sos/config"
    assert discovery_topic in published
    assert published[discovery_topic].kwargs["retain"] is True
    config = json.loads(published[discovery_topic].args[1])
    assert config["name"] == "SOS"
    assert config["unique_id"] == "site-id_sos"
    assert config["device"]["identifiers"] == ["site-id"]
    assert config["payload_press"] == "sos"
    assert config.get("retain", False) is False
    assert config["command_topic"] == f"{topic_prefix}/site-id/siren/command"
    mqtt_client.client.subscribe.assert_any_call(config["command_topic"])
    assert config["command_topic"] in mqtt_business.SUBSCRIBE_TOPICS

    response = Response()
    response.status_code = 200
    response._content = b"{}"  # pylint: disable=protected-access
    sso = Mock()
    sso.request.return_value = (response, False)
    msg = SimpleNamespace(topic=config["command_topic"], payload=config["payload_press"].encode())

    mqtt_business.consume_mqtt_message(msg, mqtt_config, SomfyProtectApi(sso), mqtt_client)

    sso.request.assert_called_once()
    request = sso.request.call_args
    assert request.args[0] == "post"
    assert request.args[1].endswith("/v3/site/site-id/panic")
    assert request.kwargs["json"] == {"type": "silent"}


@pytest.mark.parametrize("payload", [b"panic", b"TRIGGER", b"stop"])
def test_existing_siren_commands_keep_their_behavior(payload):
    """Keep audible panic and stop commands separate from the silent SOS."""
    api = Mock(spec=SomfyProtectApi)
    msg = SimpleNamespace(topic="somfyProtect2mqtt/site-id/siren/command", payload=payload)

    mqtt_business.consume_mqtt_message(msg, {}, api, None)

    if payload == b"stop":
        api.stop_alarm.assert_called_once_with(site_id="site-id")
        api.trigger_alarm.assert_not_called()
    else:
        api.trigger_alarm.assert_called_once_with(site_id="site-id", mode="alarm")
        api.stop_alarm.assert_not_called()
