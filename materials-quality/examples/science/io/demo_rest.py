"""Serve a finite synthetic paginated REST dataset at http://127.0.0.1:8766/."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        page = int(params.get("page", ["1"])[0])
        rows = [{"sample": "A1", "result": {"value": 12}}, {"sample": "B2", "result": {"value": 34}}]
        payload = {"items": rows[page - 1 : page] if 1 <= page <= 2 else []}
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__":
    print("Synthetic demo at http://127.0.0.1:8766/; stop with Ctrl+C")
    with ThreadingHTTPServer(("127.0.0.1", 8766), Handler) as server:
        server.serve_forever()
