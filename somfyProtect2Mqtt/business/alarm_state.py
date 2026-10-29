"""Track the alarm currently in progress per site.

Somfy reports an alarm with a websocket `alarm.trespass` / `alarm.panic` message, but the
site security level polled from the API only knows `disarmed`, `partial` and `armed`.
Without this registry, the periodic site refresh overwrites `triggered` with the armed level
while the siren is still sounding.
"""

import logging
import threading
from datetime import datetime, timezone

LOGGER = logging.getLogger(__name__)

_LOCK = threading.Lock()
_ACTIVE_ALARMS: dict[str, datetime | None] = {}


def parse_api_datetime(value) -> datetime | None:
    """Parse a Somfy API timestamp such as `2022-03-14T17:17:42.000000Z`."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        LOGGER.debug(f"Unparsable alarm timestamp: {value}")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def start_alarm(site_id: str, end_at=None) -> None:
    """Register an alarm in progress, until `end_at` when Somfy provides it."""
    with _LOCK:
        _ACTIVE_ALARMS[site_id] = parse_api_datetime(end_at)


def end_alarm(site_id: str) -> None:
    """Forget the alarm in progress for a site (alarm ended or site disarmed)."""
    with _LOCK:
        _ACTIVE_ALARMS.pop(site_id, None)


def alarm_in_progress(site_id: str, now: datetime | None = None) -> bool:
    """Return True while an alarm is in progress for the site."""
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        if site_id not in _ACTIVE_ALARMS:
            return False
        end_at = _ACTIVE_ALARMS[site_id]
        if end_at is not None and now >= end_at:
            _ACTIVE_ALARMS.pop(site_id, None)
            return False
        return True
