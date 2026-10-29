"""Tests for the alarm in progress (keep `triggered` during the periodic refresh)."""

from datetime import datetime, timedelta, timezone

from business import alarm_state
from business import mqtt as business_mqtt

SITE = "site-id"
START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def setup_function():
    """Start each test without any alarm in progress."""
    alarm_state.end_alarm(SITE)


def test_alarm_lasts_until_end_at():
    """The alarm is in progress until end_at, then forgotten even without an alarm.end message."""
    alarm_state.start_alarm(SITE, _iso(START + timedelta(minutes=3)))

    assert alarm_state.alarm_in_progress(SITE, now=START + timedelta(minutes=2))
    assert not alarm_state.alarm_in_progress(SITE, now=START + timedelta(minutes=3))
    assert not alarm_state.alarm_in_progress(SITE, now=START + timedelta(minutes=2))


def test_end_alarm_clears_the_alarm():
    """Disarming or alarm.end forgets the alarm in progress."""
    alarm_state.start_alarm(SITE, None)
    alarm_state.end_alarm(SITE)

    assert not alarm_state.alarm_in_progress(SITE, now=START)


def test_missing_or_bad_end_at_keeps_the_alarm_until_cleared():
    """Without a usable end_at the alarm lasts until alarm.end or a disarm."""
    assert alarm_state.parse_api_datetime("not a date") is None
    assert alarm_state.parse_api_datetime(None) is None
    alarm_state.start_alarm(SITE, "None")

    assert alarm_state.alarm_in_progress(SITE, now=START + timedelta(days=1))


def test_periodic_refresh_keeps_the_alarm_in_progress(monkeypatch):
    """The API level (armed / partial) must not overwrite an alarm in progress; disarmed clears it."""
    published = []
    monkeypatch.setattr(
        business_mqtt, "mqtt_publish", lambda **kwargs: published.append(kwargs["payload"]["security_level"])
    )
    alarm_state.start_alarm(SITE, None)

    business_mqtt.publish_site_state(None, {}, SITE, "armed")
    business_mqtt.publish_site_state(None, {}, SITE, "disarmed")
    business_mqtt.publish_site_state(None, {}, SITE, "partial")

    assert published == ["triggered", "disarmed", "armed_night"]
