"""
Mock HTTP server for testing the HA Health Reporter integration.

Listens for POST /health requests and pretty-prints the received JSON payload.

Usage:
    python server.py [port]

    port defaults to 8765 if not specified.

Example:
    python server.py 8765
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    """Handles incoming POST requests to /health."""

    def do_POST(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] Failed to parse JSON: {exc}")
            self.send_response(400)
            self.end_headers()
            return

        # Pretty-print the received payload to stdout
        print("\n" + "=" * 60)
        print(f"Received health report at {data.get('timestamp', 'unknown time')}")
        print("=" * 60)
        print(json.dumps(data, indent=2))
        print("=" * 60 + "\n")

        # Respond 200 OK
        response = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        # Suppress default Apache-style access log — our do_POST handles output
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Mock health server listening on 0.0.0.0:{port}/health")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
