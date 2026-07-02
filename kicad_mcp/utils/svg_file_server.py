"""
Shared HTTP file server for serving SVG files to the MCP app viewer.
"""

import http.server
import os
import socket
import threading
from pathlib import Path
from typing import Optional


def _get_free_port() -> int:
    """
    Finds and returns an unused local TCP port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


IMAGE_VIEW_URI = "ui://kicad-svg-viewer/view.html"
FILE_SERVER_PORT: int = _get_free_port()

_file_server: Optional[http.server.HTTPServer] = None
_root_directory: Optional[str] = None
_file_server_lock = threading.Lock()


class _CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        """
        Adds CORS and no-cache headers to every response.
        """
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


def start_or_update_file_server(project_dir: str) -> str:
    """
    Starts the shared file server, expanding its served root to cover new project directories.
    """
    global _file_server, _root_directory

    with _file_server_lock:
        candidate_root = str(Path(project_dir).resolve().parent)

        if _file_server is None:
            _root_directory = candidate_root
            handler = lambda *args, **kwargs: _CORSRequestHandler(
                *args, directory=_root_directory, **kwargs
            )
            _file_server = http.server.HTTPServer(("localhost", FILE_SERVER_PORT), handler)
            threading.Thread(target=_file_server.serve_forever, daemon=True).start()
        else:
            try:
                common = os.path.commonpath([_root_directory, candidate_root])
            except ValueError:
                common = None 

            if common and common != _root_directory:
                _root_directory = common

    return _root_directory
