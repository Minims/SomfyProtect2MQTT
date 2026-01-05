"""WebRTC Handler for Somfy Protect Cameras"""

import asyncio
import json
import logging
import re
from fractions import Fraction
from io import BytesIO

from aiortc import (
    AudioStreamTrack,
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from business.mqtt import mqtt_publish

# Suppress ffmpeg/libav warnings at C library level
import av

# Set PyAV logging level to ERROR to suppress FFmpeg warnings
av.logging.set_level(av.logging.ERROR)

# Also suppress Python-level warnings for aiortc
logging.getLogger("libav.h264").setLevel(logging.CRITICAL)
logging.getLogger("libav.swscaler").setLevel(logging.CRITICAL)
logging.getLogger("aiortc.codecs.h264").setLevel(logging.WARNING)

LOGGER = logging.getLogger(__name__)


class SilenceAudioTrack(AudioStreamTrack):
    """Empty audio track that sends silence"""

    def __init__(self):
        super().__init__()
        self.sample_rate = 48000
        self.samples_per_frame = 960
        self._timestamp = 0
        self._start = None

    async def recv(self):
        import av
        import time

        if self._start is None:
            self._start = time.time()

        # Generate silence frame
        frame = av.AudioFrame(format="s16", layout="stereo", samples=self.samples_per_frame)
        frame.rate = self.sample_rate
        frame.pts = self._timestamp
        # Use Fraction to satisfy aiortc/av expectations for AVRational
        frame.time_base = Fraction(1, self.sample_rate)

        for p in frame.planes:
            p.update(bytes(p.buffer_size))

        self._timestamp += self.samples_per_frame

        # Wait to maintain proper timing (20ms per frame at 48kHz/960 samples)
        await asyncio.sleep(0.02)

        return frame


class WebRTCHandler:
    """Handles WebRTC connections for Somfy Protect cameras"""

    def __init__(self, mqtt_client, mqtt_config, send_websocket_callback, streaming_config=None):
        """
        Initialize WebRTC handler

        Args:
            mqtt_client: MQTT client for publishing snapshots
            mqtt_config: MQTT configuration dict
            send_websocket_callback: Callback function to send WebSocket messages
            streaming_config: Streaming configuration ("mqtt", "go2rtc", etc.)
        """
        self.mqtt_client = mqtt_client
        self.mqtt_config = mqtt_config
        self.send_websocket = send_websocket_callback
        self.streaming_config = streaming_config
        self.peer_connections = {}
        self.turn_configs = {}

        # MJPEG HTTP server for go2rtc
        self.mjpeg_frames = {}  # Store latest frame per device_id
        self.mjpeg_server = None
        self.mjpeg_port = 8090

    def store_turn_config(self, session_id, turn_data):
        """Store TURN server configuration for a session"""
        if session_id and turn_data:
            self.turn_configs[session_id] = turn_data
            LOGGER.info(f"Stored TURN config for session {session_id}: {turn_data.get('url')}")

    async def handle_offer(self, message):
        """
        Handle incoming WebRTC offer from camera

        Args:
            message: WebSocket message containing the offer
        """
        LOGGER.info(f"WEBRTC Offer: {message}")

        device_id = message.get("device_id")
        site_id = message.get("site_id")
        session_id = message.get("session_id")
        offer_data = message.get("offer")
        offer_data_clean = str(offer_data).strip("^('").strip("',)$")
        offer_data_json = json.loads(offer_data_clean)
        sdp = offer_data_json.get("sdp")
        offer_type = offer_data_json.get("type")

        # Try to fix H264 decoding issues by forcing a common profile-level-id
        new_sdp_lines = []
        for line in sdp.splitlines():
            if line.startswith("a=fmtp:") and "H264" in line:
                LOGGER.info("Original H264 fmtp line: %s", line)
                # Force a common profile-level-id
                line = re.sub(r"profile-level-id=[^;]+", "profile-level-id=42e01f", line)
                LOGGER.info("Modified H264 fmtp line: %s", line)
            new_sdp_lines.append(line)
        sdp = "\r\n".join(new_sdp_lines)

        # Build ICE servers configuration
        ice_servers = [RTCIceServer(urls=["stun:stun.l.google.com:19302"])]

        # Add TURN server if available
        turn_config = self.turn_configs.get(session_id)
        if turn_config:
            turn_url = turn_config.get("url")
            turn_username = turn_config.get("username")
            turn_password = turn_config.get("password")
            if turn_url and turn_username and turn_password:
                ice_servers.append(RTCIceServer(urls=[turn_url], username=turn_username, credential=turn_password))
                LOGGER.info(f"Added TURN server: {turn_url}")
        else:
            LOGGER.warning(f"No TURN config available for session {session_id}")

        # Create peer connection
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=ice_servers))
        self.peer_connections[session_id] = pc

        # Setup event handlers
        self._setup_event_handlers(pc, session_id, site_id, device_id)

        # Set remote description
        offer = RTCSessionDescription(sdp=sdp, type=offer_type)
        await pc.setRemoteDescription(offer)

        # Add audio track
        pc.addTrack(SilenceAudioTrack())

        # Create answer
        answer = await pc.createAnswer()

        # Modify SDP to use passive DTLS setup
        modified_sdp = answer.sdp.replace("a=setup:active", "a=setup:passive")
        answer = RTCSessionDescription(sdp=modified_sdp, type=answer.type)

        await pc.setLocalDescription(answer)

        # Wait for ICE gathering
        await self._wait_for_ice_gathering(pc)

        # Send answer and candidates
        await self._send_answer_and_candidates(pc, session_id)

    def _setup_event_handlers(self, pc, session_id, site_id, device_id):
        """Setup event handlers for peer connection"""

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            LOGGER.info(f"ICE connection state is {pc.iceConnectionState}")
            if pc.iceConnectionState == "failed":
                LOGGER.error("ICE connection failed")
                if session_id in self.peer_connections:
                    del self.peer_connections[session_id]
                await pc.close()
            elif pc.iceConnectionState == "connected":
                LOGGER.info("ICE connection established successfully!")

        @pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            LOGGER.info(f"ICE gathering state is {pc.iceGatheringState}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            LOGGER.info(f"Connection state is {pc.connectionState}")
            if pc.connectionState == "connected":
                LOGGER.info("WebRTC connection established")
            elif pc.connectionState == "failed":
                LOGGER.error("WebRTC connection failed")
                await pc.close()

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                LOGGER.info(f"New local ICE candidate generated: {candidate.candidate}")
                self._send_ice_candidate(candidate, session_id)
            else:
                LOGGER.info("All local ICE candidates have been generated (end-of-candidates)")

        @pc.on("track")
        async def on_track(track):
            LOGGER.info(f"Track received: {track.kind}")
            if track.kind == "video":
                if self.streaming_config == "mqtt":
                    LOGGER.info(f"Video track started, processing frames and publishing to MQTT")
                    topic = (
                        f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                    )
                    frame_skip_counter = 0
                    try:
                        while True:
                            try:
                                frame = await track.recv()
                                LOGGER.debug(f"Video frame received: {frame}, size={frame.width}x{frame.height}")

                                # Convert frame to JPEG and publish to MQTT.
                                try:
                                    from PIL import Image

                                    # Convert directly to PIL Image from native YUV format (more efficient)
                                    pil_img = frame.to_image()

                                    # Encode as JPEG
                                    buffer = BytesIO()
                                    pil_img.save(buffer, format="JPEG", quality=85)
                                    byte_arr = bytearray(buffer.getvalue())

                                    # Publish to MQTT
                                    mqtt_publish(
                                        mqtt_client=self.mqtt_client,
                                        topic=topic,
                                        payload=byte_arr,
                                        retain=True,
                                        is_json=False,
                                        qos=2,
                                    )
                                    LOGGER.debug(f"Published frame to MQTT topic: {topic}")
                                    frame_skip_counter = 0
                                except Exception as e:
                                    frame_skip_counter += 1
                                    # Skip frames with decoding errors (especially at start due to missing SPS/PPS)
                                    if frame_skip_counter <= 10:
                                        LOGGER.debug(
                                            f"Skipping frame due to decoding error (attempt {frame_skip_counter}): {e}"
                                        )
                                    else:
                                        LOGGER.error(f"Multiple frame decoding failures: {e}")

                            except Exception as e:
                                LOGGER.error(f"Error receiving video frame: {e}")
                                await asyncio.sleep(0.1)

                    except Exception as e:
                        LOGGER.error(f"Error receiving video frames: {e}")

                elif self.streaming_config == "go2rtc":
                    LOGGER.info(f"Video track started, streaming MJPEG for go2rtc")

                    # Start MJPEG HTTP server if not already running
                    if self.mjpeg_server is None:
                        self._start_mjpeg_server(device_id)

                    frame_skip_counter = 0
                    try:
                        from PIL import Image

                        while True:
                            try:
                                frame = await track.recv()
                                LOGGER.debug(f"Video frame received: {frame}, size={frame.width}x{frame.height}")

                                try:
                                    # Convert frame to JPEG from native YUV format (more efficient)
                                    pil_img = frame.to_image()
                                    buffer = BytesIO()
                                    pil_img.save(buffer, format="JPEG", quality=85)
                                    jpeg_bytes = buffer.getvalue()

                                    # Store latest frame for MJPEG server
                                    self.mjpeg_frames[device_id] = jpeg_bytes
                                    LOGGER.debug(f"Updated MJPEG frame for device {device_id}")
                                    frame_skip_counter = 0

                                except Exception as e:
                                    frame_skip_counter += 1
                                    # Skip frames with decoding errors (especially at start due to missing SPS/PPS)
                                    if frame_skip_counter <= 10:
                                        LOGGER.debug(
                                            f"Skipping frame due to decoding error (attempt {frame_skip_counter}): {e}"
                                        )
                                    else:
                                        LOGGER.error(f"Multiple frame decoding failures: {e}")

                            except Exception as e:
                                # Check if it's end of stream
                                if "MediaStreamError" in str(type(e).__name__) or "ended" in str(e).lower():
                                    LOGGER.info(f"Video stream ended for device {device_id}")
                                    break
                                LOGGER.error(f"Error receiving frame in go2rtc: {e}")
                                LOGGER.exception("Detailed error:")
                                await asyncio.sleep(0.1)

                    except Exception as e:
                        LOGGER.info(f"MJPEG streaming stopped for device {device_id}: {e}")

                else:
                    LOGGER.info(
                        f"Video track received but streaming_config is not 'mqtt' or 'go2rtc' (current: {self.streaming_config})"
                    )
            elif track.kind == "audio":
                LOGGER.info(f"Audio track received (ignoring)")

        # ICE connection timeout checker
        async def check_ice_connection_state():
            for i in range(20):
                await asyncio.sleep(1)
                LOGGER.debug(
                    f"ICE check ({i+1}/20): iceConnectionState={pc.iceConnectionState}, "
                    f"connectionState={pc.connectionState}"
                )
                if pc.iceConnectionState in ["connected", "completed"]:
                    LOGGER.info("ICE connection successful!")
                    return
            if pc.iceConnectionState in ["new", "checking"]:
                LOGGER.warning(f"ICE connection timeout - state stuck at {pc.iceConnectionState}, closing connection")
                await pc.close()

        asyncio.create_task(check_ice_connection_state())

    async def _wait_for_ice_gathering(self, pc, max_wait=2):
        """Wait for ICE gathering to complete"""
        for _ in range(max_wait * 10):
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)
        LOGGER.info(f"ICE gathering state: {pc.iceGatheringState}")

    async def _send_answer_and_candidates(self, pc, session_id):
        """Send SDP answer and ICE candidates separately (trickle ICE)"""
        answer_sdp = pc.localDescription.sdp
        answer_sdp_lines = answer_sdp.split("\r\n")
        answer_sdp_no_candidates = []

        # Strip candidates from SDP
        for line in answer_sdp_lines:
            if not line.startswith("a=candidate:") and line != "a=end-of-candidates":
                answer_sdp_no_candidates.append(line)

        clean_answer_sdp = "\r\n".join(answer_sdp_no_candidates)
        candidates_stripped = answer_sdp.count("a=candidate:")
        LOGGER.info(f"Stripped {candidates_stripped} candidates from answer SDP")

        # Log SDP for debugging
        LOGGER.info(f"Full clean answer SDP:\n{clean_answer_sdp}")

        if "a=setup:" in clean_answer_sdp:
            setup_line = [line for line in answer_sdp_no_candidates if "a=setup:" in line]
            LOGGER.info(f"DTLS setup in answer: {setup_line}")

        # Send answer
        response = {
            "key": "video.webrtc.answer",
            "session_id": session_id,
            "answer": {"type": pc.localDescription.type, "sdp": clean_answer_sdp},
            "forward": True,
        }
        self.send_websocket(response)
        LOGGER.info("Answer sent")

        # Send ICE candidates separately
        sdp_lines = pc.localDescription.sdp.split("\r\n")
        current_mid = None
        mid_index = {}
        m_line_count = -1

        for line in sdp_lines:
            if line.startswith("m="):
                m_line_count += 1
            elif line.startswith("a=mid:"):
                current_mid = line.split("a=mid:")[1]
                mid_index[current_mid] = m_line_count
            elif line.startswith("a=candidate:"):
                candidate_str = line.split("a=")[1]
                if current_mid is not None:
                    candidate_msg = {
                        "key": "video.webrtc.candidate",
                        "session_id": session_id,
                        "candidate": {
                            "sdp": candidate_str,
                            "sdpMid": current_mid,
                            "sdpMLineIndex": mid_index.get(current_mid, 0),
                        },
                        "forward": True,
                    }
                    self.send_websocket(candidate_msg)
                    LOGGER.info(f"Sent ICE candidate for mid={current_mid}: {candidate_str[:50]}...")

        LOGGER.info("All ICE candidates sent via trickle ICE")

    def _send_ice_candidate(self, candidate, session_id):
        """Send ICE candidate via WebSocket"""
        message = {
            "key": "video.webrtc.candidate",
            "session_id": session_id,
            "candidate": {
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
                "sdp": candidate.candidate,
            },
            "forward": True,
        }
        self.send_websocket(message)

    async def add_remote_candidate(self, session_id, candidate_data):
        """
        Add remote ICE candidate from camera

        Args:
            session_id: WebRTC session ID
            candidate_data: Candidate data from WebSocket message
        """
        if not session_id or not candidate_data:
            LOGGER.warning(f"Missing session_id or candidate data")
            return

        pc = self.peer_connections.get(session_id)
        if not pc:
            LOGGER.warning(f"No peer connection found for session {session_id}")
            return

        try:
            candidate = RTCIceCandidate(
                sdpMid=candidate_data.get("sdpMid"),
                sdpMLineIndex=candidate_data.get("sdpMLineIndex"),
                candidate=candidate_data.get("sdp"),
            )
            await pc.addIceCandidate(candidate)
            LOGGER.info(f"Added remote ICE candidate: {candidate_data.get('sdp', '')[:60]}...")
        except Exception as e:
            LOGGER.error(f"Failed to add remote ICE candidate: {e}")

    async def close_session(self, session_id):
        """
        Close WebRTC session and cleanup

        Args:
            session_id: WebRTC session ID
        """
        if session_id and session_id in self.peer_connections:
            try:
                pc = self.peer_connections[session_id]
                await pc.close()
                del self.peer_connections[session_id]
                if session_id in self.turn_configs:
                    del self.turn_configs[session_id]
                LOGGER.info(f"Closed and removed peer connection for session {session_id}")
            except Exception as e:
                LOGGER.error(f"Error closing peer connection: {e}")

    def _start_mjpeg_server(self, device_id):
        """Start HTTP server for MJPEG streaming"""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        handler = self

        class MJPEGHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress HTTP logs

            def do_GET(self):
                # Extract device_id from path: /camera/{device_id}
                path_parts = self.path.strip("/").split("/")
                if len(path_parts) >= 2 and path_parts[0] == "camera":
                    device_id = path_parts[1]

                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()

                    try:
                        while True:
                            if device_id in handler.mjpeg_frames:
                                jpeg_bytes = handler.mjpeg_frames[device_id]
                                self.wfile.write(b"--frame\r\n")
                                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                                self.wfile.write(f"Content-Length: {len(jpeg_bytes)}\r\n\r\n".encode())
                                self.wfile.write(jpeg_bytes)
                                self.wfile.write(b"\r\n")
                            import time

                            time.sleep(0.033)  # ~30 fps
                    except:
                        pass
                else:
                    self.send_error(404)

        server = HTTPServer(("0.0.0.0", self.mjpeg_port), MJPEGHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.mjpeg_server = server
        LOGGER.info(f"MJPEG HTTP server started on http://0.0.0.0:{self.mjpeg_port}/camera/{device_id}")
