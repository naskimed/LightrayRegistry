"""Localhost HTTP API (stdlib http.server, 127.0.0.1:8377) — humans/CLI submissions + reads.

POST /events                     submit an EventDraft
GET  /health | /state | /spend | /blocks/<id> | /budget/<lineage> | /cards/<id> | /constants/<series>

v1 security posture (recorded decision): unauthenticated on localhost; actor strings
honor-system; hardening deferred until a second human/agent actor exists.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config
from ..export import spend_view
from ..schemas.envelope import EventDraft
from .writer import Writer


def make_handler(writer: Writer):
    state = writer.state

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, obj) -> None:
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = self.path.strip("/").split("/")
            if self.path == "/health":
                self._send(200, {"ok": True, "as_of_seq": state.as_of_seq,
                                 "head": state.head_hash,
                                 "open_cycle": state.open_cycle,
                                 "halt": config.halt_path().exists(),
                                 "readonly": config.readonly_path().exists()})
            elif self.path == "/state":
                d = state.model_dump(mode="json")
                d["dedup"] = sorted(state.dedup)
                self._send(200, d)
            elif self.path == "/spend":
                self._send(200, spend_view(state))
            elif parts[0] == "blocks" and len(parts) == 2:
                b = state.blocks.get(parts[1])
                self._send(200 if b else 404, b or {"error": "unknown block"})
            elif parts[0] == "budget" and len(parts) == 2:
                lin = state.lineages.get(parts[1])
                self._send(200 if lin else 404,
                           (lin or {}).get("budget") or {"error": "unknown lineage"})
            elif parts[0] == "cards" and len(parts) == 2:
                c = state.cards.get(parts[1])
                self._send(200 if c else 404, c or {"error": "unknown card"})
            elif parts[0] == "constants" and len(parts) == 2:
                c = state.constants.get(parts[1])
                self._send(200 if c else 404, c or {"error": "unknown series"})
            else:
                self._send(404, {"error": "unknown path"})

        def do_POST(self):
            if self.path != "/events":
                self._send(404, {"error": "unknown path"})
                return
            if config.readonly_path().exists():
                self._send(503, {"error": "READONLY: no new proposals accepted"})
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                draft = EventDraft.model_validate(json.loads(self.rfile.read(n)))
            except Exception as e:
                self._send(400, {"accepted": False, "code": "SCHEMA_INVALID", "reason": str(e)})
                return
            decision, event = writer.submit(draft).result()
            self._send(200 if decision.accepted else 422, {
                "accepted": decision.accepted, "code": decision.code,
                "reason": decision.reason, "dedup_noop": decision.dedup_noop,
                "seq": event.seq if event else None,
                "event_hash": event.event_hash if event else None,
            })

    return Handler


class Api(threading.Thread):
    def __init__(self, writer: Writer):
        super().__init__(name="api", daemon=True)
        self.server = ThreadingHTTPServer((config.API_HOST, config.API_PORT),
                                          make_handler(writer))

    def run(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        self.server.shutdown()
