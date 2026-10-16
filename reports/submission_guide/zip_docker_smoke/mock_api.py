import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def reply(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply({"data": {"id": "qwen/qwen3.7-flash", "endpoints": [
            {"pricing": {"prompt": "0.0000002", "completion": "0.0000008"}}]}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if (self.path.startswith("/denied/")
            or self.headers.get("Authorization") != "Bearer smoke-placeholder"
            or body.get("model") != "qwen/qwen3.7-flash"):
            self.reply({"error": {"code": "unauthorized"}}, 401)
            return
        program = {"code": "result=num(sheets[0], 'B2')", "format": {"kind": "integer"}}
        self.reply({"model": "qwen/qwen3.7-flash", "choices": [
            {"message": {"content": json.dumps(program)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 50, "cost": 0}})

HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
