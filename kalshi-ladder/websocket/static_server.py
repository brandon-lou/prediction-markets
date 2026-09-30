"""Serves the ladder/ folder over http://127.0.0.1 so the UI can call Kalshi directly.

Kalshi's WAF rejects requests carrying `Origin: null` (what a page loaded from file://
sends), but allow-lists http://localhost:* with full CORS headers. Serving the UI over
localhost is therefore what lets the market finder fetch Kalshi's public endpoints from
the browser, instead of routing search through the trading process.

This runs on a plain daemon thread and makes no Kalshi calls of its own — nothing here
touches the asyncio loop or the shared API throttler that order placement uses.
"""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

LADDER_DIR = Path(__file__).resolve().parent.parent / "ladder"


class _QuietHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler logs every request to stderr, which would bury the
    fill/orderbook prints the trading console relies on."""

    def log_message(self, format, *args) -> None:  # noqa: A002 - signature is fixed by the base class
        pass


def start_static_server(port: int, directory: Path = LADDER_DIR) -> Optional[ThreadingHTTPServer]:
    """Start the UI file server in the background. Returns None if the port is taken.

    Binds loopback only — the ladder is a trading UI and has no business being reachable
    from the LAN.
    """
    handler = functools.partial(_QuietHandler, directory=str(directory))
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        print(f">> UI file server could not bind port {port} ({exc}). "
              f"Ladder search will be unavailable; open ladder/index.html directly to trade without it.")
        return None

    threading.Thread(target=httpd.serve_forever, daemon=True, name="ladder-static").start()
    print(f">> Ladder UI running on http://localhost:{port}/")
    return httpd
