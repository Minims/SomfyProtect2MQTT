# WebRTC hang-up recovery design

## Intent
Automatically recover a WebRTC camera stream when Somfy closes the current session with `video.webrtc.hang_up`, while avoiding reconnect loops and protecting newer sessions.

## Scope
- Store the site/device context for owned WebRTC sessions.
- Retry a server-initiated hang-up after 2, 5, and 15 seconds.
- Cancel pending retries when a newer session starts or the WebSocket shuts down.
- Do not retry an explicit user stop or an unrelated/late hang-up.

## Approaches
1. **Reconnect in the WebSocket handler (chosen):** it already owns Somfy messages, session ownership, and `start_webrtc_stream`; no API-layer changes.
2. Reconnect in `WebRTCHandler`: rejected because it lacks the WebSocket request context and would couple media cleanup to signalling.
3. Unbounded immediate retry: rejected because it can loop against a server-side refusal and create repeated camera sessions.

## Design decisions
- A per-device reconnect task is tracked by device ID.
- A session context maps session ID to `site_id` and `device_id`.
- A hang-up only schedules recovery when it matches the currently owned session.
- Each retry gets a fresh session ID through `start_webrtc_stream`.
- A new owned session cancels the old device retry task.

## Non-goals
- Bypassing Somfy server-side session limits.
- Retrying explicit user stops.
- Guaranteeing recovery when the camera or Somfy API is unavailable.
