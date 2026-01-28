"""Somfy Protect WebSocket Client.

This module handles real-time communication with Somfy Protect servers
via WebSocket for instant event notifications.
"""

import asyncio
import json
import logging
import ssl
import time

import websocket
from business.mqtt import mqtt_publish
from mqtt import MQTTClient
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso
from somfy_protect.webrtc_handler import WebRTCHandler
from websocket import WebSocketApp

# Import handlers from dedicated modules
from somfy_protect.websocket.handlers import (
    # Alarm handlers
    handle_security_level_change,
    handle_alarm_trespass,
    handle_alarm_panic,
    handle_alarm_domestic_fire,
    handle_alarm_domestic_fire_end,
    handle_alarm_end,
    # Device handlers
    handle_device_status,
    handle_device_ring_door_bell,
    handle_device_missed_call,
    handle_device_doorlock_triggered,
    handle_keyfob_presence,
    handle_device_gate_triggered_from_monitor,
    handle_device_gate_triggered_from_mobile,
    handle_device_answered_call_from_monitor,
    handle_device_answered_call_from_mobile,
    # Video handlers
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

WEBSOCKET = "wss://websocket.myfox.io/events/websocket?token="
LOGGER = logging.getLogger(__name__)


class SomfyProtectWebsocket:
    """Somfy Protect WebSocket Client.
    
    Handles real-time communication with Somfy Protect servers for
    instant event notifications (alarms, device status, video streams).
    
    Attributes:
        mqtt_client: MQTT client for publishing events
        mqtt_config: MQTT configuration dictionary
        streaming_config: Video streaming configuration
        api: Somfy Protect API instance
        sso: SSO authentication handler
        webrtc_handler: WebRTC session handler
    """

    def __init__(
        self,
        sso: SomfyProtectSso,
        config: dict,
        mqtt_client: MQTTClient,
        api: SomfyProtectApi,
        debug: bool = False,
    ):
        """Initialize WebSocket client.
        
        Args:
            sso: SSO authentication handler
            config: Application configuration
            mqtt_client: MQTT client instance
            api: Somfy Protect API instance
            debug: Enable debug logging
        """
        self.mqtt_client = mqtt_client
        self.mqtt_config = config.get("mqtt")
        self.streaming_config = config.get("streaming")
        self.api = api
        self.sso = sso
        self.time = time.time()

        # Initialize WebRTC handler
        self.webrtc_handler = WebRTCHandler(
            mqtt_client=mqtt_client,
            mqtt_config=self.mqtt_config,
            send_websocket_callback=self.send_websocket_message,
            streaming_config=self.streaming_config,
        )

        # Create a dedicated event loop for async operations
        self.loop = asyncio.new_event_loop()
        import threading
        self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.loop_thread.start()

        if debug:
            websocket.enableTrace(True)
            LOGGER.debug(f"Opening websocket connection to {WEBSOCKET}")
        
        self.token = self.sso.request_token()
        websocket.setdefaulttimeout(5)
        self._websocket = WebSocketApp(
            f"{WEBSOCKET}{self.token.get('access_token')}",
            on_open=self.on_open,
            on_message=self._on_message_wrapper,
            on_error=self.on_error,
            on_close=self.on_close,
            on_ping=self.on_ping,
            on_pong=self.on_pong,
        )

        # Message callback routing
        self._callbacks = {
            # Alarm events
            "security.level.change": lambda msg: handle_security_level_change(self, msg),
            "alarm.trespass": lambda msg: handle_alarm_trespass(self, msg),
            "alarm.panic": lambda msg: handle_alarm_panic(self, msg),
            "alarm.domestic.fire": lambda msg: handle_alarm_domestic_fire(self, msg),
            "alarm.domestic.fire.end": lambda msg: handle_alarm_domestic_fire_end(self, msg),
            "alarm.end": lambda msg: handle_alarm_end(self, msg),
            # Presence events
            "presence_out": lambda msg: handle_keyfob_presence(self, msg),
            "presence_in": lambda msg: handle_keyfob_presence(self, msg),
            # Device events
            "device.status": lambda msg: handle_device_status(self, msg),
            "device.ring_door_bell": lambda msg: handle_device_ring_door_bell(self, msg),
            "device.missed_call": lambda msg: handle_device_missed_call(self, msg),
            "device.doorlock_triggered": lambda msg: handle_device_doorlock_triggered(self, msg),
            "device.gate_triggered_from_mobile": lambda msg: handle_device_gate_triggered_from_mobile(self, msg),
            "device.gate_triggered_from_monitor": lambda msg: handle_device_gate_triggered_from_monitor(self, msg),
            "answered_call_from_monitor": lambda msg: handle_device_answered_call_from_monitor(self, msg),
            "answered_call_from_mobile": lambda msg: handle_device_answered_call_from_mobile(self, msg),
            # Video events
            "video.stream.ready": lambda msg: handle_video_stream_ready(self, msg),
            "video.webrtc.offer": lambda msg: handle_video_webrtc_offer(self, msg),
            "video.webrtc.start": lambda msg: handle_video_webrtc_start(self, msg),
            "video.webrtc.session": lambda msg: handle_video_webrtc_session(self, msg),
            "video.webrtc.answer": lambda msg: handle_video_webrtc_answer(self, msg),
            "video.webrtc.candidate": lambda msg: handle_video_webrtc_candidate(self, msg),
            "video.webrtc.turn.config": lambda msg: handle_video_webrtc_turn_config(self, msg),
            "video.webrtc.keep_alive": lambda msg: handle_video_webrtc_keep_alive(self, msg),
            "video.webrtc.hang_up": lambda msg: handle_video_webrtc_hang_up(self, msg),
        }

    def _run_event_loop(self):
        """Run the event loop in a dedicated thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _on_message_wrapper(self, ws_app, message):
        """Wrapper to handle async on_message in sync context."""
        try:
            future = asyncio.run_coroutine_threadsafe(self.on_message(ws_app, message), self.loop)
            future.result()
        except Exception as e:
            LOGGER.error(f"Error in message wrapper: {e}")

    def run_forever(self):
        """Run the WebSocket connection loop."""
        self._websocket.run_forever(
            ping_timeout=10,
            ping_interval=15,
            reconnect=5,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        LOGGER.info("Running Forever")

    def close(self):
        """Close the WebSocket connection."""
        LOGGER.info("Closing Websocket")
        # Clean up WebRTC sessions
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.webrtc_handler.close_all_sessions(), self.loop
            )
            future.result(timeout=5)
        except Exception as e:
            LOGGER.warning(f"Error closing WebRTC sessions: {e}")

        # Stop the event loop
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=2)

        # Close websocket
        if self._websocket:
            self._websocket.close()

        # Refresh token for reconnection
        try:
            self.token = self.sso.request_token()
            self._websocket = WebSocketApp(
                f"{WEBSOCKET}{self.token.get('access_token')}",
                on_open=self.on_open,
                on_message=self._on_message_wrapper,
                on_error=self.on_error,
                on_close=self.on_close,
                on_ping=self.on_ping,
                on_pong=self.on_pong,
            )
        except Exception as e:
            LOGGER.error(f"Error refreshing token: {e}")

    def start_webrtc_stream(self, site_id: str, device_id: str, session_id: str = None):
        """Start a WebRTC video stream.
        
        Args:
            site_id: Site identifier
            device_id: Device (camera) identifier
            session_id: Optional session ID for resuming
        """
        future = asyncio.run_coroutine_threadsafe(
            self.webrtc_handler.start_stream(site_id, device_id, session_id), self.loop
        )
        return future.result()

    def on_ping(self, ws_app, message):
        """Handle WebSocket ping."""
        LOGGER.debug(f"Got a Ping! {message}")

    def on_pong(self, ws_app, message):
        """Handle WebSocket pong."""
        LOGGER.debug(f"Got a Pong! {message}")
        # Close and reconnect after 30 minutes
        if (time.time() - self.time) > 1800:
            self.close()

    async def on_message(self, ws_app, message):
        """Handle incoming WebSocket messages.
        
        Routes messages to appropriate handlers based on message key.
        
        Args:
            ws_app: WebSocket application
            message: Raw message string
        """
        if "websocket.connection.ready" in message:
            LOGGER.info("Websocket Connection is READY")
            return

        if "websocket.error.token" in message:
            self._websocket.close()
            return

        LOGGER.debug(f"Message: {message}")

        message_json = json.loads(message)
        
        # Send acknowledgment
        ack = {
            "ack": True,
            "message_id": message_json["message_id"],
            "client": "Android",
        }
        self.send_websocket_message(ack)
        
        # Handle default message (publish to MQTT)
        self._handle_default_message(message_json)
        
        # Route to specific handler
        message_key = message_json.get("key")
        if message_key in self._callbacks:
            callback = self._callbacks[message_key]
            result = callback(message_json)
            if asyncio.iscoroutine(result):
                await result
        else:
            LOGGER.debug(f"Unknown message: {message}")

    def _handle_default_message(self, message: dict):
        """Publish message to MQTT as default handling.
        
        Args:
            message: Parsed message dictionary
        """
        LOGGER.info(f"[default] Read Message {message}")
        topic_suffix = message.get("key")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        
        if not site_id:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{topic_suffix}"
        elif not device_id:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{topic_suffix}"
        else:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/{topic_suffix}"
        
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=message, retain=True)

    def on_error(self, ws_app, error):
        """Handle WebSocket errors."""
        LOGGER.error(f"Error in the websocket connection: {error}")

    def on_open(self, ws_app):
        """Handle WebSocket connection opened."""
        LOGGER.info("Opened connection")

    def on_close(self, ws_app, close_status_code, close_msg):
        """Handle WebSocket connection closed."""
        LOGGER.info(f"Websocket on_close, status {close_status_code} => {close_msg}")

    def send_websocket_message(self, message: dict):
        """Send a message via the WebSocket connection.
        
        Args:
            message: Message dictionary to send
        """
        if self._websocket and self._websocket.sock and self._websocket.sock.connected:
            self._websocket.send(json.dumps(message))
            LOGGER.debug(f"Sent on Websocket: {message}")
        else:
            LOGGER.warning(f"WebSocket is not connected. Unable to send message: {message}")
