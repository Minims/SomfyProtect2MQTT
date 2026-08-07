"""Tests for setup_logger() — permission error fallback (issue #267)."""

import logging
from unittest.mock import patch

from utils import setup_logger


def test_setup_logger_creates_file_handler(tmp_path):
    """setup_logger adds a FileHandler when the path is writable."""
    log_file = str(tmp_path / "test.log")
    setup_logger(debug=False, filename=log_file)

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert file_handlers, "Expected at least one FileHandler"
    # Clean up handlers to avoid polluting other tests.
    for h in file_handlers:
        h.close()
        root.removeHandler(h)


def test_setup_logger_fallback_on_permission_error(tmp_path):
    """setup_logger falls back to stdout-only when FileHandler raises OSError."""
    # Point to a path inside a directory that does not exist and cannot be created.
    bad_path = "/nonexistent_dir_that_cannot_be_created/test.log"

    setup_logger(debug=False, filename=bad_path)

    root = logging.getLogger()
    # Must have at least one StreamHandler.
    stream_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert stream_handlers, "Expected at least one StreamHandler after fallback"
    # Must NOT have a FileHandler pointing to the bad path.
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and h.baseFilename == bad_path]
    assert not file_handlers, "FileHandler for bad path must not be present after fallback"


def test_setup_logger_fallback_when_filehandler_raises(tmp_path):
    """setup_logger gracefully handles OSError from FileHandler constructor."""
    with patch("logging.FileHandler", side_effect=OSError("mocked permission denied")):
        setup_logger(debug=True, filename="irrelevant.log")

    root = logging.getLogger()
    stream_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert stream_handlers, "Expected StreamHandler even when FileHandler raises"


def test_setup_logger_sets_debug_level(tmp_path):
    """setup_logger sets DEBUG level when debug=True."""
    log_file = str(tmp_path / "debug.log")
    setup_logger(debug=True, filename=log_file)

    assert logging.getLogger().level == logging.DEBUG

    # Cleanup
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)


def test_setup_logger_sets_info_level(tmp_path):
    """setup_logger sets INFO level when debug=False."""
    log_file = str(tmp_path / "info.log")
    setup_logger(debug=False, filename=log_file)

    assert logging.getLogger().level == logging.INFO

    # Cleanup
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
