"""Local HTTP application for IncidentPilot. Uses only Python's standard library."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent import run_live, run_offline
from rag import build_dense_index, index_stats
from tools import SCENARIOS, ALLOWED_ACTIONS

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 20_000
PENDING: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "IncidentPilot/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _headers(self, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
        self.end_headers()

    def _json(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers("application/json; charset=utf-8", status)
        self.wfile.write(encoded)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError(f"Request body must be between 1 and {MAX_BODY} bytes.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json.")
        body = self.rfile.read(length)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Request must be a JSON object.")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            try:
                data = (STATIC / "index.html").read_bytes()
            except OSError:
                self._json({"error": "The dashboard file is missing."}, 500)
                return
            self._headers("text/html; charset=utf-8")
            self.wfile.write(data)
            return
        if path == "/api/status":
            self._json({"ok": True, "live_available": bool(os.environ.get("OPENAI_API_KEY")), "demo_available": True, "retrieval": index_stats()})
            return
        if path == "/api/scenarios":
            cases = [{"id": key, "title": value["title"], "description": value["description"]} for key, value in SCENARIOS.items()]
            self._json({"scenarios": cases})
            return
        self._json({"error": "Not found."}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, 400)
            return

        if path == "/api/run":
            scenario = payload.get("scenario")
            mode = payload.get("mode", "offline")
            note = payload.get("note", "")
            if scenario not in SCENARIOS:
                self._json({"error": "Choose a listed synthetic scenario."}, 400)
                return
            if not isinstance(note, str) or len(note) > 1200:
                self._json({"error": "Operator note must be text under 1,200 characters."}, 400)
                return
            try:
                if mode == "offline":
                    result = run_offline(scenario)
                elif mode == "live":
                    result = run_live(scenario, note)
                else:
                    self._json({"error": "Mode must be offline or live."}, 400)
                    return
            except (ValueError, RuntimeError) as error:
                self._json({"error": str(error)}, 422)
                return
            proposal = result.get("proposal")
            if proposal and proposal.get("proposal_id"):
                PENDING[proposal["proposal_id"]] = proposal
                while len(PENDING) > 256:
                    PENDING.pop(next(iter(PENDING)))
            self._json(result)
            return

        if path == "/api/index":
            try:
                result = build_dense_index(force=bool(payload.get("force", False)))
            except (ValueError, RuntimeError) as error:
                self._json({"error": str(error)}, 422)
                return
            self._json(result)
            return

        if path == "/api/approve":
            proposal_id = payload.get("proposal_id")
            decision = payload.get("decision")
            if not isinstance(proposal_id, str) or not isinstance(decision, str):
                self._json({"error": "A proposal ID and decision are required."}, 400)
                return
            proposal = PENDING.get(proposal_id)
            if proposal is None:
                self._json({"error": "This proposal is missing, expired, or already processed."}, 404)
                return
            if decision not in {"approve", "reject"}:
                self._json({"error": "Decision must be approve or reject."}, 400)
                return
            if proposal.get("action") not in ALLOWED_ACTIONS:
                self._json({"error": "This action is not allowed."}, 403)
                return
            PENDING.pop(proposal_id, None)
            if decision == "approve":
                status = "approved_simulation"
                message = f"Approval recorded. ‘{ALLOWED_ACTIONS[proposal['action']]}’ was simulated in the isolated demo. No real service changed."
            else:
                status = "rejected"
                message = "Proposal rejected. No action was simulated."
            self._json({"proposal_id": proposal_id, "status": status, "message": message})
            return

        self._json({"error": "Not found."}, 404)


def main() -> None:
    host = os.environ.get("INCIDENTPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if host not in {"127.0.0.1", "localhost"} and os.environ.get("INCIDENTPILOT_ALLOW_PUBLIC") != "1":
        raise SystemExit("Refusing to bind to a non-loopback address. Set INCIDENTPILOT_ALLOW_PUBLIC=1 only for a deliberately configured deployment.")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"IncidentPilot listening at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping IncidentPilot.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
