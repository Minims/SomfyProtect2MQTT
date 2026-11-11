"""Limit repeated H264 startup warnings without muting decoder failures."""

import logging
import threading
import time


class H264DecodeWarningFilter(logging.Filter):
    """Report H264 no-frame warnings at most every five seconds per decoder thread."""

    def __init__(self) -> None:
        super().__init__()
        self._decoder = threading.local()

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if (
            record.levelno != logging.WARNING
            or logging.getLogger(record.name).getEffectiveLevel() <= logging.DEBUG
            or not message.startswith("RTCRtpReceiver(video) failed to decode H264 frame:")
            or "[h264] no frame!" not in message
        ):
            return True
        now = time.monotonic()
        if now - getattr(self._decoder, "last_warning", float("-inf")) < 5:
            self._decoder.suppressed += 1
            return False
        suppressed = getattr(self._decoder, "suppressed", 0)
        if suppressed:
            record.msg = message + f" ({suppressed} similar warnings suppressed)"
            record.args = ()
        self._decoder.last_warning = now
        self._decoder.suppressed = 0
        return True
