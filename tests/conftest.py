"""
Smoke test fixtures for swift-mcp-gateway.

Starts the MCP server on a random port against a mock proxy,
then tears it all down after the session.
"""

import threading
import time
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _MockProxyHandler(BaseHTTPRequestHandler):
    """Minimal mock of the token server /proxy endpoint."""

    def log_message(self, *args):  # silence access logs in test output
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = json.dumps({"mock": True, "path": self.path}).encode()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = json.dumps({"mock": True, "path": self.path, "accepted": True}).encode()
        self.wfile.write(body)


@pytest.fixture(scope="session")
def mock_proxy():
    """Start a mock proxy server. Returns its base URL."""
    server = HTTPServer(("127.0.0.1", 0), _MockProxyHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}"
    server.shutdown()
