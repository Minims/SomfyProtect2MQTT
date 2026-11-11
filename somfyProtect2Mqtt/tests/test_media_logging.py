"""Keep repeated decoder warnings useful without hiding ongoing failures."""

import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from utils.log_filters import H264DecodeWarningFilter


def warning(codec="H264", error="[h264] no frame!"):
    return logging.LogRecord(
        "aiortc.rtcrtpreceiver",
        logging.WARNING,
        __file__,
        1,
        "RTCRtpReceiver(%s) failed to decode %s frame: %s",
        ("video", codec, error),
        None,
    )


def test_repeated_no_frame_warnings_are_counted_and_periodically_reported():
    limiter = H264DecodeWarningFilter()
    with patch("utils.log_filters.time.monotonic", side_effect=[0, 0.1, 0.2, 5]):
        assert limiter.filter(warning())
        assert not limiter.filter(warning())
        assert not limiter.filter(warning())
        repeated = warning()
        assert limiter.filter(repeated)
    assert "2 similar warnings suppressed" in repeated.getMessage()


def test_other_decoder_errors_are_not_suppressed():
    limiter = H264DecodeWarningFilter()
    for _ in range(3):
        assert limiter.filter(warning(error="corrupt slice"))
        assert limiter.filter(warning(codec="VP8"))
        error = warning()
        error.levelno = logging.ERROR
        assert limiter.filter(error)


def test_debug_mode_retains_every_decode_warning():
    limiter = H264DecodeWarningFilter()
    with patch.object(logging.getLogger("aiortc.rtcrtpreceiver"), "getEffectiveLevel", return_value=logging.DEBUG):
        assert all(limiter.filter(warning()) for _ in range(3))


def test_each_decoder_thread_reports_its_first_warning():
    limiter = H264DecodeWarningFilter()
    assert limiter.filter(warning())
    assert not limiter.filter(warning())
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(limiter.filter, warning()).result()
