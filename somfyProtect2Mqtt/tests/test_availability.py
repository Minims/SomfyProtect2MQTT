"""Tests for the availability of the Somfy Protect API (entities unavailable when the cloud cannot be reached)."""

import json
import sys
from http.client import RemoteDisconnected
from types import ModuleType, SimpleNamespace

import pytest
import requests
from business import availability, update_sites_status
from business.availability import ApiAvailability, availability_topic, with_availability


def _tracker(threshold=2):
    published = []
    return ApiAvailability(published.append, failures_before_offline=threshold), published


def test_online_on_first_success_then_only_on_changes():
    """The first answer publishes online; further answers publish nothing."""
    tracker, published = _tracker()

    tracker.report_success()
    tracker.report_success()

    assert published == ["online"]
    assert tracker.online is True


def test_offline_after_consecutive_failures_only():
    """A single failure is tolerated; the threshold in a row publishes offline once."""
    tracker, published = _tracker(threshold=2)
    tracker.report_success()

    tracker.report_failure("timeout")
    assert published == ["online"]

    tracker.report_success()
    tracker.report_failure("timeout")
    assert published == ["online"], "a success in between resets the count"

    tracker.report_failure("dns")
    tracker.report_failure("dns")
    assert published == ["online", "offline"]
    assert tracker.online is False


def test_back_online_after_outage():
    """The first answer after an outage publishes online again."""
    tracker, published = _tracker(threshold=1)

    tracker.report_failure("dns")
    tracker.report_success()

    assert published == ["offline", "online"]


def test_republish_only_known_state():
    """After a broker reconnection the known state is published again; nothing before it is known."""
    tracker, published = _tracker(threshold=1)

    tracker.republish()
    assert not published

    tracker.report_failure("dns")
    tracker.republish()
    assert published == ["offline", "offline"]


def test_discovery_payload_follows_availability_topic():
    """Discovery payloads get the availability topic; removal payloads stay empty."""
    topic = availability_topic({"topic_prefix": "custom"})

    assert topic == "custom/availability"
    assert availability_topic(None) == "somfyProtect2mqtt/availability"
    assert with_availability({"name": "Maison"}, topic) == {
        "name": "Maison",
        "availability_topic": "custom/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    assert with_availability({}, topic) == {}
    assert with_availability({"name": "Maison"}, None) == {"name": "Maison"}


def test_helpers_ignore_clients_without_tracking():
    """Clients without availability tracking (e.g. in tests) are ignored."""
    availability.report_api_success(None)
    availability.report_api_failure(SimpleNamespace(), "dns")


class _FailingApi:
    def __init__(self, error):
        self.error = error

    def get_site(self, site_id):
        """Fail like the API would."""
        raise self.error


def test_site_refresh_reports_network_errors(monkeypatch):
    """Network errors while polling the site count as failures; the API answering counts as a success."""
    tracker, published = _tracker(threshold=2)
    client = SimpleNamespace(availability=tracker)
    monkeypatch.setattr("business.publish_site_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("business._publish_site_history", lambda *args, **kwargs: None)

    update_sites_status(_FailingApi(requests.exceptions.ConnectionError("dns")), client, {}, ["site"])
    update_sites_status(_FailingApi(RemoteDisconnected("closed")), client, {}, ["site"])
    assert published == ["offline"]

    site = SimpleNamespace(label="Maison", security_level="disarmed")
    api = SimpleNamespace(get_site=lambda site_id: site)
    update_sites_status(api, client, {}, ["site"])
    assert published == ["offline", "online"]


@pytest.mark.parametrize(
    "error",
    [
        KeyError("security_level"),
        ValueError("invalid data"),
        requests.exceptions.JSONDecodeError("invalid JSON", "", 0),
    ],
)
def test_data_errors_do_not_mark_offline(error):
    """A malformed answer is not an outage."""
    tracker, published = _tracker(threshold=1)
    client = SimpleNamespace(availability=tracker)

    update_sites_status(_FailingApi(error), client, {}, ["site"])

    assert not published


def test_recovery_publishes_all_site_states_before_online(monkeypatch):
    """Recovered entities must receive fresh states before becoming available."""
    tracker, published = _tracker(threshold=1)
    tracker.report_failure("dns")
    published.clear()
    client = SimpleNamespace(
        availability=tracker,
        client=SimpleNamespace(publish=lambda topic, payload, **kwargs: published.append((topic, json.loads(payload)))),
    )
    api = SimpleNamespace(get_site=lambda site_id: SimpleNamespace(label=site_id, security_level="armed"))
    monkeypatch.setattr("business._publish_site_history", lambda *args: None)

    update_sites_status(api, client, {}, ["home", "second-home"])

    assert published == [
        ("somfyProtect2mqtt/home/state", {"security_level": "armed_away"}),
        ("somfyProtect2mqtt/second-home/state", {"security_level": "armed_away"}),
        "online",
    ]


def test_multi_site_outage_counts_once_per_poll():
    """Two failing sites in one poll must not exhaust the two-poll tolerance."""
    tracker, published = _tracker()
    tracker.report_success()
    published.clear()
    client = SimpleNamespace(availability=tracker)
    api = _FailingApi(requests.exceptions.ConnectionError("dns"))

    update_sites_status(api, client, {}, ["home", "second-home"])
    assert published == []

    update_sites_status(api, client, {}, ["home", "second-home"])
    assert published == ["offline"]


def test_successful_site_prevents_global_outage(monkeypatch):
    """A partial outage must not toggle global availability on each poll."""
    tracker, published = _tracker()
    tracker.report_success()
    published.clear()
    client = SimpleNamespace(availability=tracker)

    def get_site(site_id):
        if site_id != "reachable":
            raise requests.exceptions.ConnectionError("timeout")
        return SimpleNamespace(label=site_id, security_level="disarmed")

    api = SimpleNamespace(get_site=get_site)
    monkeypatch.setattr("business.publish_site_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("business._publish_site_history", lambda *args: None)

    for _ in range(2):
        update_sites_status(api, client, {}, ["home", "second-home", "reachable"])

    assert published == []


@pytest.mark.parametrize("error", [OSError("publish failed"), ValueError("invalid payload")])
def test_failed_state_publish_does_not_restore_availability(monkeypatch, error):
    """An API answer alone must not expose the retained state as current."""
    tracker, published = _tracker(threshold=1)
    tracker.report_failure("dns")
    published.clear()
    client = SimpleNamespace(availability=tracker)
    api = SimpleNamespace(get_site=lambda site_id: SimpleNamespace(label=site_id, security_level="armed"))

    def fail_publish(*args, **kwargs):
        raise error

    monkeypatch.setattr("business.publish_site_state", fail_publish)

    update_sites_status(api, client, {}, ["home"])

    assert published == []
    assert tracker.online is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (requests.exceptions.ConnectionError("dns"), ["offline"]),
        (requests.exceptions.JSONDecodeError("invalid JSON", "", 0), []),
    ],
)
def test_startup_counts_network_errors_only(monkeypatch, error, expected):
    """Malformed startup responses must not count as network failures either."""
    # The API loop does not use the optional OpenCV camera backend.
    monkeypatch.setitem(sys.modules, "cv2", ModuleType("cv2"))
    import main  # pylint: disable=import-outside-toplevel

    tracker, published = _tracker(threshold=1)
    client = SimpleNamespace(availability=tracker)

    def fail_init(**kwargs):
        raise error

    monkeypatch.setattr(main, "SomfyProtect2Mqtt", fail_init)

    main.somfy_protect_loop({}, client, None)

    assert published == expected
