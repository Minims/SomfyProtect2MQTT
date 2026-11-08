"""Tests for the availability of the Somfy Protect API (entities unavailable when the cloud cannot be reached)."""

from http.client import RemoteDisconnected
from types import SimpleNamespace

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


def test_data_errors_do_not_mark_offline():
    """A malformed answer is not an outage."""
    tracker, published = _tracker(threshold=1)
    client = SimpleNamespace(availability=tracker)

    update_sites_status(_FailingApi(KeyError("security_level")), client, {}, ["site"])

    assert not published
