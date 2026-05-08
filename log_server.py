#!/usr/bin/env python3
"""
Simple CORS-enabled log server for intercepting browser console output.
Run: python3 log_server.py
Then paste the companion snippet into the Gemini tab's DevTools console.
"""
import http.server
import socketserver
import urllib.parse
import json
import os
from datetime import datetime

PORT = 9999
LOG_FILE = "/tmp/gemini_agent_console.log"


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default access logs; we print our own
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/log":
            qs = urllib.parse.parse_qs(parsed.query)
            msg = qs.get("m", [""])[0]
            self._log_message(msg)
            self._respond_json({"status": "ok"})
        elif parsed.path == "/":
            self._respond_status()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/log":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                msg = data.get("message", body)
            except Exception:
                msg = body
            self._log_message(msg)
            self._respond_json({"status": "ok"})
        else:
            self.send_error(404)

    def _log_message(self, msg):
        timestamp = datetime.now().isoformat()
        line = f"[{timestamp}] {msg}\n"
        print(line.strip())
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

    def _respond_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _respond_status(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        log_content = ""
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log_content = f.read()
        html = f"""<!DOCTYPE html>
<html>
<head>
<title>Gemini Agent Console Log</title>
<meta http-equiv="refresh" content="5">
<style>
body {{ font-family: monospace; white-space: pre-wrap; background: #1e1e1e; color: #d4d4d4; padding: 20px; margin: 0; }}
.timestamp {{ color: #858585; }}
</style>
</head>
<body>{log_content}</body>
</html>"""
        self.wfile.write(html.encode())


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
        print(f"Log server running at http://localhost:{PORT}/")
        print(f"Logs written to: {LOG_FILE}")
        httpd.serve_forever()
