"""RTMPS Camera to JPEG"""

import logging

import cv2

LOGGER = logging.getLogger(__name__)


class VideoCamera(object):
    """OpenCV-backed video capture helper."""
    def __init__(self, url: str):
        """Initialize the camera stream.

        Args:
            url (str): Video stream URL.
        """
        self.video = cv2.VideoCapture(url)

    def __del__(self):
        """Release camera resources on deletion."""
        self.video.release()

    def is_opened(self) -> bool:
        """Return True if the stream is open."""
        return self.video.isOpened()

    def release(self) -> None:
        """Release the video capture."""
        self.video.release()

    def get_frame(self) -> bytes | None:
        """Get a single JPEG-encoded frame.

        Returns:
            bytes | None: JPEG-encoded frame bytes, or None on failure.
        """
        try:
            ret, image = self.video.read()
            if not ret:
                return None
            ret, jpeg = cv2.imencode(".jpg", image)
            if not ret:
                return None
            return jpeg.tobytes()
        except Exception as exc:
            LOGGER.debug("Unable to get Frame: %s", exc)
            return None
