"""WebSocket message handlers package.

This package contains handlers organized by event type:
- alarm: Alarm events (trespass, panic, fire, etc.)
- device: Device events (status, doorbell, doorlock, keyfob, etc.)
- video: Video/streaming events (stream ready, WebRTC signaling)
"""

from somfy_protect.websocket.handlers.alarm import (
    handle_security_level_change,
    handle_alarm_trespass,
    handle_alarm_panic,
    handle_alarm_domestic_fire,
    handle_alarm_domestic_fire_end,
    handle_alarm_end,
)

from somfy_protect.websocket.handlers.device import (
    handle_device_status,
    handle_device_ring_door_bell,
    handle_device_missed_call,
    handle_device_doorlock_triggered,
    handle_keyfob_presence,
    handle_device_gate_triggered_from_monitor,
    handle_device_gate_triggered_from_mobile,
    handle_device_answered_call_from_monitor,
    handle_device_answered_call_from_mobile,
)

from somfy_protect.websocket.handlers.video import (
    handle_video_stream_ready,
    handle_video_webrtc_offer,
    handle_video_webrtc_candidate,
    handle_video_webrtc_hang_up,
    handle_video_webrtc_keep_alive,
    handle_video_webrtc_session,
    handle_video_webrtc_start,
    handle_video_webrtc_answer,
    handle_video_webrtc_turn_config,
)

__all__ = [
    # Alarm handlers
    "handle_security_level_change",
    "handle_alarm_trespass",
    "handle_alarm_panic",
    "handle_alarm_domestic_fire",
    "handle_alarm_domestic_fire_end",
    "handle_alarm_end",
    # Device handlers
    "handle_device_status",
    "handle_device_ring_door_bell",
    "handle_device_missed_call",
    "handle_device_doorlock_triggered",
    "handle_keyfob_presence",
    "handle_device_gate_triggered_from_monitor",
    "handle_device_gate_triggered_from_mobile",
    "handle_device_answered_call_from_monitor",
    "handle_device_answered_call_from_mobile",
    # Video handlers
    "handle_video_stream_ready",
    "handle_video_webrtc_offer",
    "handle_video_webrtc_candidate",
    "handle_video_webrtc_hang_up",
    "handle_video_webrtc_keep_alive",
    "handle_video_webrtc_session",
    "handle_video_webrtc_start",
    "handle_video_webrtc_answer",
    "handle_video_webrtc_turn_config",
]
