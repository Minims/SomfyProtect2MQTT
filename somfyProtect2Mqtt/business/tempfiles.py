"""Temporary file helpers for media handling."""

import os
import tempfile
from collections.abc import Iterable


def write_temp_bytes(chunks: Iterable[bytes], suffix: str) -> str:
    """Write streamed bytes to a secure temporary file.

    Args:
        chunks (Iterable[bytes]): Streamed byte chunks.
        suffix (str): Temporary file suffix.

    Returns:
        str: Temporary file path.
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as temp_file:
            for chunk in chunks:
                if chunk:
                    temp_file.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


def remove_temp_file(path: str | None) -> None:
    """Remove a temporary file if it still exists."""
    if path and os.path.exists(path):
        os.remove(path)
