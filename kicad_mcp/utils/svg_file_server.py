"""
Shared HTTP file server for serving SVG files to the MCP app viewer.
"""

import http.server
import socket
import threading
from typing import Optional


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


IMAGE_VIEW_URI = "ui://kicad-svg-viewer/view.html"
FILE_SERVER_PORT: int = _get_free_port()

_file_server: Optional[http.server.HTTPServer] = None
_file_server_lock = threading.Lock()


class _CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # suppress access logs


def start_or_update_file_server(directory: str) -> None:
    """Start the file server if not running, or point it to a new directory."""
    global _file_server

    with _file_server_lock:
        if _file_server is None:
            handler = lambda *args, **kwargs: _CORSRequestHandler(
                *args, directory=directory, **kwargs
            )
            _file_server = http.server.HTTPServer(("localhost", FILE_SERVER_PORT), handler)
            threading.Thread(target=_file_server.serve_forever, daemon=True).start()
        else:
            _file_server.RequestHandlerClass = lambda *args, **kwargs: _CORSRequestHandler(
                *args, directory=directory, **kwargs
            )
