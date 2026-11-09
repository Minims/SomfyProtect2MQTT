"""Availability of the Somfy Protect API, published over MQTT for Home Assistant.

Without it, every entity keeps showing its last state when the Somfy cloud cannot be reached
(internet outage, DNS failure, Somfy maintenance): an alarm that looks armed may not be, and
commands sent from Home Assistant are lost without any visible error.
"""

import logging
import threading
from typing import Callable, Optional

LOGGER = logging.getLogger(__name__)

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"
# Count one failure per site polling cycle (every `delay_site` seconds, 60 s minimum),
# regardless of the number of configured sites.
FAILURES_BEFORE_OFFLINE = 2


def availability_topic(mqtt_config: Optional[dict]) -> str:
    """Topic holding `online` / `offline` (retained)."""
    return f"{(mqtt_config or {}).get('topic_prefix', 'somfyProtect2mqtt')}/availability"


def with_availability(config: Optional[dict], topic: Optional[str]) -> Optional[dict]:
    """Return a discovery payload that follows the availability topic.

    Empty payloads (used to remove an entity) and missing topics are left untouched.
    """
    if not config or not topic:
        return config
    return {
        **config,
        "availability_topic": topic,
        "payload_available": PAYLOAD_ONLINE,
        "payload_not_available": PAYLOAD_OFFLINE,
    }


class ApiAvailability:
    """Track whether the Somfy Protect API answers, and publish each change."""

    def __init__(self, publish: Callable[[str], None], failures_before_offline: int = FAILURES_BEFORE_OFFLINE):
        self._publish = publish
        self._threshold = max(1, failures_before_offline)
        self._lock = threading.Lock()
        self._failures = 0
        self._online: Optional[bool] = None
        self.generation = 0

    @property
    def online(self) -> Optional[bool]:
        """True / False once known, None before the first answer or failure."""
        return self._online

    def report_success(self, expected_generation: int | None = None) -> None:
        """Publish online after a state refresh on the current MQTT connection.

        Args:
            expected_generation (int | None): Connection generation captured before the refresh.
                Ignore success if that connection has since been replaced.
        """
        with self._lock:
            if expected_generation is not None and expected_generation != self.generation:
                return
            self._failures = 0
            if self._online is True:
                return
            self._online = True
            LOGGER.info(f"Somfy Protect API reachable, publishing {PAYLOAD_ONLINE}")
            self._publish(PAYLOAD_ONLINE)

    def report_failure(self, error: object = None) -> None:
        """The API did not answer: publish `offline` after enough failures in a row."""
        with self._lock:
            self._failures += 1
            if self._online is False or self._failures < self._threshold:
                return
            self._online = False
            LOGGER.warning(f"Somfy Protect API unreachable ({error}), publishing {PAYLOAD_OFFLINE}")
            self._publish(PAYLOAD_OFFLINE)

    def reset_connection(self) -> None:
        """Publish offline until a state refresh completes on this MQTT connection."""
        with self._lock:
            self.generation += 1
            self._failures = 0
            self._online = False
            self._publish(PAYLOAD_OFFLINE)


def report_api_success(mqtt_client, expected_generation: int | None = None) -> None:
    """Report a published site state, if the client tracks availability.

    Args:
        mqtt_client (MQTTClient): Client owning the availability tracker.
        expected_generation (int | None): MQTT generation captured before refreshing sites.
    """
    availability = getattr(mqtt_client, "availability", None)
    if availability is not None:
        availability.report_success(expected_generation)


def report_api_failure(mqtt_client, error: object = None) -> None:
    """Report a failed API call, if the client tracks availability."""
    availability = getattr(mqtt_client, "availability", None)
    if availability is not None:
        availability.report_failure(error)
