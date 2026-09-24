from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from .canonical import dumps, loads
from .identity import verify
from .protocol import parse_command
from .ui_auth import AuthManager, SESSION_TTL_SECONDS
from .ui_projection import build_public_state
from .readiness import readiness_report
from .season_verifier import verify_season_artifacts
from .season_insights import descriptive_scoreboard, replay_timeline
from .store import Store
from .interop import runtime_capabilities, runtime_fingerprint

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "ui"
DEFAULT_DB = Path(os.environ.get(
    "FLOP_EMPIRES_DB",
    Path(os.environ.get("LOCALAPPDATA", ROOT)) / "FLOPEmpires" / "season0-runtime-v1" / "season0.sqlite3",
))
WORLD = ROOT / "season" / "world-season-0-v1.json"
ACTIVATION = ROOT / "season" / "SEASON-0-ACTIVATION-v1.json"
RECOVERY = ROOT / "season" / "SEASON-0-RECOVERY-v1.json"
LAUNCH = ROOT / "season" / "SEASON-0-LAUNCH-AUTHORIZATION-v1.json"
MANIFEST = ROOT / "season" / "SEASON-0-MANIFEST-FREEZE-V2-CANDIDATE.json"
RUNNER_STATUS = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "FLOPEmpires" / "season0-runtime-v1" / "runner-status.json"
AUTH = AuthManager()
COOKIE_NAME = "flop_empires_session"
TECHNOCORE_ORIGIN = "https://technocore.chat"

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        # pythonw has no stderr; hidden service requests must not depend on console logging.
        return

    def _json(self, status: int, payload: dict, *, cookie: str | None = None) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie(); jar.load(raw)
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _session_did(self) -> str | None:
        return AUTH.session_did(self._session_token())

    def _read_json(self, limit: int = 64_000) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("INVALID_CONTENT_LENGTH") from exc
        if length < 1 or length > limit:
            raise ValueError("INVALID_BODY_SIZE")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("JSON_OBJECT_REQUIRED")
        return value

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json(200, build_public_state(DEFAULT_DB, WORLD, ACTIVATION, self._session_did())); return
        if path == "/api/interop/capabilities":
            self._json(200, runtime_capabilities(MANIFEST, ACTIVATION, LAUNCH)); return
        if path == "/api/interop/fingerprint":
            revision = os.environ.get("FLOP_EMPIRES_REVISION", "unknown")
            self._json(200, runtime_fingerprint(MANIFEST, ACTIVATION, revision)); return
        if path in {"/api/readiness","/api/verification","/api/replay","/api/scoreboard"}:
            store=Store(DEFAULT_DB, readonly=True)
            try:
                if path=="/api/readiness": payload=readiness_report(store,MANIFEST,ACTIVATION,WORLD,RUNNER_STATUS,RECOVERY,LAUNCH)
                elif path=="/api/verification": payload=verify_season_artifacts(store,MANIFEST,ACTIVATION,WORLD,RECOVERY,LAUNCH)
                elif path=="/api/replay": payload=replay_timeline(store)
                else: payload=descriptive_scoreboard(store,WORLD)
            finally: store.close()
            self._json(200,payload); return
        if path.startswith("/api/receipt/"):
            did=self._session_did()
            if not did: self._json(401,{"error":"AUTH_REQUIRED"}); return
            request_id=path.removeprefix("/api/receipt/")
            store=Store(DEFAULT_DB, readonly=True)
            try:
                row=store.one("SELECT receipt_json FROM requests WHERE actor_did=? AND request_id=?",(did,request_id))
                out=store.one("SELECT status,publish_ref,readback_verified,attempts FROM receipt_outbox WHERE actor_did=? AND request_id=? ORDER BY attempts DESC LIMIT 1",(did,request_id))
            finally: store.close()
            if not row: self._json(404,{"status":"NOT_SEEN"}); return
            self._json(200,{"status":"ACCEPTED_BY_REFEREE","receipt":json.loads(row[0]),"publication":dict(out) if out else None}); return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/auth/challenge":
                body = self._read_json()
                did = body.get("did")
                if not isinstance(did, str):
                    raise ValueError("DID_REQUIRED")
                self._json(200, AUTH.issue(did))
                return
            if path == "/api/auth/verify":
                body = self._read_json()
                required = {"challenge_id", "did", "signature"}
                if set(body) != required or not all(isinstance(body[k], str) for k in required):
                    raise ValueError("AUTH_FIELDS_INVALID")
                token, expires_at = AUTH.verify_challenge(body["challenge_id"], body["did"], body["signature"])
                secure = "; Secure" if os.environ.get("FLOP_EMPIRES_UI_SECURE_COOKIE") == "1" else ""
                cookie = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}{secure}"
                self._json(200, {"ok": True, "did": body["did"], "expires_at": expires_at}, cookie=cookie)
                return
            if path == "/api/auth/logout":
                AUTH.logout(self._session_token())
                self._json(200, {"ok": True}, cookie=f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                return
            if path == "/api/action":
                self._handle_action()
                return
            self._json(404, {"error": "NOT_FOUND"})
        except (ValueError, RuntimeError) as exc:
            self._json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self._json(400, {"error": "INVALID_JSON"})

    def _handle_action(self) -> None:
        did = self._session_did()
        if not did:
            self._json(401, {"error": "AUTH_REQUIRED"})
            return
        body = self._read_json()
        if set(body) != {"did", "sig", "nonce", "text"}:
            raise ValueError("SIGNED_ENVELOPE_FIELDS_INVALID")
        if not all(isinstance(body[k], str) and body[k] for k in body):
            raise ValueError("SIGNED_ENVELOPE_VALUES_INVALID")
        if body["did"] != did:
            raise ValueError("SESSION_DID_MISMATCH")
        activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))
        if RECOVERY.is_file():
            recovery=json.loads(RECOVERY.read_text(encoding="utf-8")); room=recovery["duplex_namespace"]
        else:
            recovery=None; room=activation["actions_namespace"]
        text = body["text"]
        if len(text) > 12_000 or len(body["nonce"]) > 128:
            raise ValueError("SIGNED_ENVELOPE_TOO_LARGE")
        if not verify(did, f"{room}|{body['nonce']}|{text}".encode("utf-8"), body["sig"]):
            raise ValueError("INVALID_ACTION_SIGNATURE")
        parsed = loads(text)
        if dumps(parsed) != text:
            raise ValueError("NON_CANONICAL_ACTION_TEXT")
        if not isinstance(parsed, dict) or set(parsed) != {"season_id", "command"}:
            raise ValueError("ACTION_WRAPPER_INVALID")
        if parsed["season_id"] != activation["season_id"] or not isinstance(parsed["command"], dict):
            raise ValueError("WRONG_SEASON")
        command = parsed["command"]
        try:
            parse_command(command)
        except ValueError as exc:
            raise ValueError("MALFORMED_COMMAND") from exc
        if command.get("actor_did") != did:
            raise ValueError("ACTOR_FIELD_SPOOFING")
        try:
            response = httpx.post(
                f"{TECHNOCORE_ORIGIN}/r/{quote(room, safe='')}",
                json=body,
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            self._json(502, {"error": "TECHNOCORE_UNAVAILABLE", "detail": type(exc).__name__})
            return
        payload: object
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:4000]
        status = 200 if 200 <= response.status_code < 300 else 502
        self._json(status, {"ok": status == 200, "upstream_status": response.status_code, "body": payload})


def main() -> None:
    host = os.environ.get("FLOP_EMPIRES_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("FLOP_EMPIRES_UI_PORT", "8876"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"FLOP Empires UI: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
