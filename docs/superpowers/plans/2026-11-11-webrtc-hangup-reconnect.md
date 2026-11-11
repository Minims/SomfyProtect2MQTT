# WebRTC hang-up recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-establish a WebRTC camera session after a server-initiated `video.webrtc.hang_up` using bounded retries.

**Architecture:** Keep signalling recovery in `SomfyProtectWebsocket`. Track session context by session ID and one pending reconnect task per device. A newer session or shutdown cancels pending recovery.

**Tech Stack:** Python 3.14, asyncio, pytest, existing WebSocket/WebRTC classes.

**Spec:** `docs/superpowers/specs/2026-11-11-webrtc-hangup-reconnect-design.md`

## Global Constraints

- Retry delays are exactly 2, 5, and 15 seconds.
- Retry only an owned, currently active session.
- Never retry an explicit user stop.
- Use existing `start_webrtc_stream`; add no dependency.

## Review Focus

- A late hang-up from an old session must not restart a newer session.
- A second hang-up must not create duplicate reconnect tasks.
- WebSocket shutdown must cancel delayed reconnects.
- A new session must cancel a pending retry before it fires.
- Retry exhaustion must leave no pending task or stale session ownership.

---

### Task 1: Track WebRTC session context and reconnect scheduling

**Files:**
- Modify: `somfyProtect2Mqtt/somfy_protect/websocket/__init__.py`
- Test: `somfyProtect2Mqtt/tests/test_webrtc_sessions.py`

**Interfaces:**
- Produces per-session context and per-device reconnect task state used by the hang-up handler.

- [ ] **Step 1: Write failing tests** for retrying a matching hang-up with delays `[2, 5, 15]`, ignoring a late hang-up, deduplicating a second hang-up, cancelling on a newer session, and stopping after three retries.
- [ ] **Step 2: Run the focused tests and verify they fail** because the current handler closes sessions without scheduling recovery.
- [ ] **Step 3: Implement the minimum state and recovery coroutine** in the WebSocket class. Store `session_id -> (site_id, device_id)`, track `device_id -> asyncio.Task`, schedule only matching owned sessions, use fresh `start_webrtc_stream` calls, and clear state in completion/cancellation paths.
- [ ] **Step 4: Run focused tests and verify they pass.**
- [ ] **Step 5: Run the complete test suite.**
- [ ] **Step 6: Commit** with `fix(webrtc): recover server-closed camera sessions`.

### Task 2: Integrate lifecycle cancellation and documentation

**Files:**
- Modify: `somfyProtect2Mqtt/somfy_protect/websocket/__init__.py`
- Modify: `README.md`
- Test: `somfyProtect2Mqtt/tests/test_webrtc_sessions.py`

**Interfaces:**
- Consumes Task 1 reconnect task state.

- [ ] **Step 1: Add failing lifecycle tests** for shutdown cancellation and explicit stop behavior.
- [ ] **Step 2: Run them and verify the expected failures.**
- [ ] **Step 3: Cancel reconnect tasks from the existing WebSocket close path and document bounded hang-up recovery and its limits in README.
- [ ] **Step 4: Run the focused and complete suites.**
- [ ] **Step 5: Run Black, isort, and Pylint error checks.**
- [ ] **Step 6: Commit** with `docs(webrtc): describe hang-up recovery`.
