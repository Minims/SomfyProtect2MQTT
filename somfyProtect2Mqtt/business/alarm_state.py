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

# Publishers also hold this lock while calling the registry helpers.
ALARM_STATE_LOCK = threading.RLock()
_ACTIVE_ALARMS: dict[str, datetime | None] = {}
_SITE_REVISIONS: dict[str, int] = {}


def get_site_revision(site_id: str) -> int:
    """Return the site's revision to capture before a REST refresh."""
    with ALARM_STATE_LOCK:
        return _SITE_REVISIONS.get(site_id, 0)


def invalidate_site_refresh(site_id: str) -> None:
    """Invalidate pending REST responses after an alarm or security event."""
    with ALARM_STATE_LOCK:
        _SITE_REVISIONS[site_id] = _SITE_REVISIONS.get(site_id, 0) + 1


def parse_api_datetime(value: object) -> datetime | None:
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


def start_alarm(site_id: str, end_at: str | None = None) -> None:
    """Register an alarm in progress, until `end_at` when Somfy provides it."""
    with ALARM_STATE_LOCK:
        invalidate_site_refresh(site_id)
        _ACTIVE_ALARMS[site_id] = parse_api_datetime(end_at)


def end_alarm(site_id: str) -> None:
    """Forget the alarm in progress for a site (alarm ended or site disarmed)."""
    with ALARM_STATE_LOCK:
        invalidate_site_refresh(site_id)
        _ACTIVE_ALARMS.pop(site_id, None)


def alarm_in_progress(site_id: str, now: datetime | None = None) -> bool:
    """Return True while an alarm is in progress for the site."""
    now = now or datetime.now(timezone.utc)
    with ALARM_STATE_LOCK:
        if site_id not in _ACTIVE_ALARMS:
            return False
        end_at = _ACTIVE_ALARMS[site_id]
        if end_at is not None and now >= end_at:
            _ACTIVE_ALARMS.pop(site_id, None)
            return False
        return True
