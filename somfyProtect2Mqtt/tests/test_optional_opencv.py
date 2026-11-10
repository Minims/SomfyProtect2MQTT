"""Startup and missing RTMPS backend behavior without OpenCV."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_help_without_opencv():
    """The standard runtime must start without the optional video dependency."""
    script = """
import runpy
import sys
sys.modules['cv2'] = None
sys.argv = ['main.py', '--help']
runpy.run_path('somfyProtect2Mqtt/main.py', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "somfyProtect2Mqtt")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--configuration" in result.stdout


def test_rtmps_without_opencv_reports_missing_dependency():
    """A missing optional backend must not terminate the I/O worker."""
    script = """
import sys
sys.modules['cv2'] = None
from somfy_protect.websocket.handlers.video import stream_video_to_mqtt
stream_video_to_mqtt(None, 'site', 'camera', 'rtmps://example.invalid/stream')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "somfyProtect2Mqtt")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "requirements/docker.txt" in result.stderr
