"""Tests for SomfyProtectSso rate-limit handling (issue #248).

Focuses on _wait_for_rate_limit_reset_locked(): the sleep must happen
*outside* the _oauth_lock so that other threads are not blocked.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from somfy_protect.sso import SomfyProtectSso


def _make_sso() -> SomfyProtectSso:
    """Create a minimal SSO instance without any real OAuth calls."""
    with patch("somfy_protect.sso.OAuth2Session"), patch("somfy_protect.sso.build_retry_adapter"):
        sso = SomfyProtectSso.__new__(SomfyProtectSso)
        sso.username = "user@example.com"
        sso.password = "password"
        sso.token_cache_path = "token.json"
        sso._oauth_lock = threading.RLock()
        sso._token_retry_after_seconds = 0
        sso._token_rate_limit_deadline = 0.0
        sso.token_updater = None
        sso._oauth = MagicMock()
        import base64

        from somfy_protect.sso import CLIENT_ID, CLIENT_SECRET

        sso.client_id = base64.b64decode(CLIENT_ID).decode("utf-8")
        sso.client_secret = base64.b64decode(CLIENT_SECRET).decode("utf-8")
    return sso


class TestRateLimitSleepReleasesLock:
    """_wait_for_rate_limit_reset_locked() must release the lock during sleep."""

    def test_lock_is_released_during_sleep(self):
        """A second thread can acquire _oauth_lock while rate-limit sleep is in progress."""
        sso = _make_sso()

        # Set a short rate-limit deadline in the future.
        sleep_duration = 0.15
        sso._token_rate_limit_deadline = time.monotonic() + sleep_duration
        sso._token_retry_after_seconds = sleep_duration

        lock_acquired_during_sleep = threading.Event()
        lock_acquire_failed = threading.Event()

        def _try_acquire_lock():
            # Give the main thread a moment to enter the sleep.
            time.sleep(0.05)
            # Try acquiring the lock with a tight timeout — should succeed
            # because the sleeping thread has released it.
            acquired = sso._oauth_lock.acquire(blocking=True, timeout=0.5)
            if acquired:
                lock_acquired_during_sleep.set()
                sso._oauth_lock.release()
            else:
                lock_acquire_failed.set()

        helper = threading.Thread(target=_try_acquire_lock, daemon=True)

        with sso._oauth_lock:
            helper.start()
            sso._wait_for_rate_limit_reset_locked()

        helper.join(timeout=2)
        assert (
            lock_acquired_during_sleep.is_set()
        ), "Lock was NOT released during rate-limit sleep — other threads would be blocked"
        assert not lock_acquire_failed.is_set()

    def test_lock_reacquired_after_sleep(self):
        """The lock is held again after _wait_for_rate_limit_reset_locked() returns."""
        sso = _make_sso()

        sleep_duration = 0.05
        sso._token_rate_limit_deadline = time.monotonic() + sleep_duration
        sso._token_retry_after_seconds = sleep_duration

        with sso._oauth_lock:
            sso._wait_for_rate_limit_reset_locked()
            # If the lock is held again, acquiring with timeout=0 from another
            # thread must fail.
            result = []

            def _try():
                result.append(sso._oauth_lock.acquire(blocking=True, timeout=0.05))

            t = threading.Thread(target=_try, daemon=True)
            t.start()
            t.join(timeout=1)

        assert result == [False], "Lock should be held by the caller after sleep ends"

    def test_no_sleep_when_deadline_passed(self):
        """No sleep occurs when the rate-limit deadline is already in the past."""
        sso = _make_sso()
        sso._token_rate_limit_deadline = time.monotonic() - 1.0  # past

        start = time.monotonic()
        with sso._oauth_lock:
            sso._wait_for_rate_limit_reset_locked()
        elapsed = time.monotonic() - start

        assert elapsed < 0.05, f"Unexpected sleep: {elapsed:.3f}s"

    def test_no_sleep_when_no_rate_limit(self):
        """No sleep when deadline is 0 (never rate-limited)."""
        sso = _make_sso()
        sso._token_rate_limit_deadline = 0.0

        start = time.monotonic()
        with sso._oauth_lock:
            sso._wait_for_rate_limit_reset_locked()
        elapsed = time.monotonic() - start

        assert elapsed < 0.05, f"Unexpected sleep: {elapsed:.3f}s"
