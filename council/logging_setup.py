"""Logging setup. Logs go to stderr so stdout stays clean for command output (JSON, Markdown).

Never log secrets or raw portfolio rows; log counts, ids and file hashes instead.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    root = logging.getLogger("council")
    root.setLevel(numeric)
    if not any(getattr(h, "_council", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._council = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        root.propagate = False
    else:
        for h in root.handlers:
            h.setLevel(numeric)
            if getattr(h, "_council", False) and isinstance(h, logging.StreamHandler):
                # Follow the current stderr (matters when it is captured, e.g. in tests). Assign the
                # attribute instead of setStream(), which would flush a stream that may be closed.
                h.acquire()
                try:
                    h.stream = sys.stderr
                finally:
                    h.release()
