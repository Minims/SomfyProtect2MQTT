"""Alarm event ordering and stale REST responses."""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import business
import pytest
from business import alarm_state
from business import mqtt as business_mqtt

# Alarm handlers do not use the optional OpenCV camera backend.
with patch.dict(sys.modules, {"cv2": ModuleType("cv2")}):
    from somfy_protect.websocket.handlers import alarm

SITE = "alarm-events-site"


@pytest.fixture
def websocket_client():
    """Record actual MQTT payloads without connecting to a broker."""
    alarm_state.end_alarm(SITE)
    published = []
    client = SimpleNamespace(publish=lambda topic, payload, **kwargs: published.append(json.loads(payload)))
    api = SimpleNamespace(get_site=lambda site_id: SimpleNamespace(security_level="armed", label="Home"))
    websocket = SimpleNamespace(mqtt_client=SimpleNamespace(client=client), mqtt_config={}, api=api)
    yield websocket, published
    alarm_state.end_alarm(SITE)


@pytest.mark.parametrize("level", ["armed", "partial"])
def test_intrusion_survives_refresh_until_alarm_end(websocket_client, level):
    """Keep triggered until a real end event, then restore the API state."""
    websocket, published = websocket_client
    end_at = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
    alarm.alarm_trespass(websocket, {"site_id": SITE, "type": "alarm", "end_at": end_at})
    business_mqtt.publish_site_state(websocket.mqtt_client, {}, SITE, level)
    alarm.alarm_end(websocket, {"site_id": SITE})

    assert published == [
        {"security_level": "triggered"},
        {"security_level": "triggered"},
        {"security_level": "armed_away"},
    ]


@pytest.mark.parametrize("event", ["disarm", "end", "start"])
def test_refresh_and_events_publish_in_order(websocket_client, event):
    """A delayed MQTT enqueue must not overwrite a newer alarm event."""
    websocket, published = websocket_client
    if event != "start":
        alarm.alarm_trespass(websocket, {"site_id": SITE, "type": "alarm"})
    published.clear()
    enqueue_started = threading.Event()
    resume_enqueue = threading.Event()
    event_started = threading.Event()
    event_finished = threading.Event()
    publish = websocket.mqtt_client.client.publish

    def delayed_publish(topic, payload, **kwargs):
        if threading.current_thread().name.startswith("refresh"):
            enqueue_started.set()
            assert resume_enqueue.wait(5)
        publish(topic, payload, **kwargs)

    def deliver_event():
        event_started.set()
        if event == "disarm":
            alarm.security_level_change(websocket, {"site_id": SITE, "security_level": "disarmed"})
        elif event == "end":
            alarm.alarm_end(websocket, {"site_id": SITE})
        else:
            alarm.alarm_panic(websocket, {"site_id": SITE})
        event_finished.set()

    websocket.mqtt_client.client.publish = delayed_publish
    with ThreadPoolExecutor(1, thread_name_prefix="refresh") as refresher, ThreadPoolExecutor(1) as events:
        refresh = refresher.submit(business_mqtt.update_site, websocket.api, websocket.mqtt_client, {}, SITE)
        try:
            assert enqueue_started.wait(5)
            event_task = events.submit(deliver_event)
            assert event_started.wait(5)
            event_finished.wait(0.1)
        finally:
            resume_enqueue.set()
        refresh.result(timeout=5)
        event_task.result(timeout=5)

    expected_last_state = {"disarm": "disarmed", "end": "armed_away", "start": "triggered"}[event]
    assert published[-1] == {"security_level": expected_last_state}


@pytest.mark.parametrize("periodic", [False, True])
@pytest.mark.parametrize("event", ["start", "disarm", "arm", "end"])
def test_refresh_discards_response_overtaken_by_event(websocket_client, monkeypatch, periodic, event):
    """An in-flight REST request cannot undo a later WebSocket event."""
    websocket, published = websocket_client
    fetching = threading.Event()
    resume_fetch = threading.Event()

    def stale_get_site(site_id):
        if threading.current_thread().name.startswith("refresh"):
            fetching.set()
            assert resume_fetch.wait(5)
            return SimpleNamespace(security_level="armed" if event == "disarm" else "disarmed", label="Home")
        return SimpleNamespace(security_level="armed", label="Home")

    websocket.api.get_site = stale_get_site
    monkeypatch.setattr(business, "_publish_site_history", lambda *args: None)
    refresh = business.update_sites_status if periodic else business_mqtt.update_site
    with ThreadPoolExecutor(1, thread_name_prefix="refresh") as executor:
        task = executor.submit(refresh, websocket.api, websocket.mqtt_client, {}, [SITE] if periodic else SITE)
        try:
            assert fetching.wait(5)
            if event == "start":
                alarm.alarm_trespass(websocket, {"site_id": SITE, "type": "alarm"})
            elif event == "end":
                alarm.alarm_end(websocket, {"site_id": SITE})
            else:
                level = "disarmed" if event == "disarm" else "armed"
                alarm.security_level_change(websocket, {"site_id": SITE, "security_level": level})
            expected = list(published)
        finally:
            resume_fetch.set()
        task.result(timeout=5)

    assert published == expected
    assert alarm_state.alarm_in_progress(SITE) == (event == "start")


def test_event_on_another_site_does_not_cancel_refresh(websocket_client):
    """Only events for the refreshed site invalidate its REST response."""
    websocket, published = websocket_client

    def get_site(site_id):
        alarm.security_level_change(websocket, {"site_id": "other-site", "security_level": "disarmed"})
        return SimpleNamespace(security_level="armed")

    websocket.api.get_site = get_site
    business_mqtt.update_site(websocket.api, websocket.mqtt_client, {}, SITE)

    assert published == [{"security_level": "disarmed"}, {"security_level": "armed_away"}]
