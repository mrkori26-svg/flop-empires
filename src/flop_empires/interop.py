from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from .canonical import sha256
from .models import Receipt
from .receipts import verify_receipt

SCHEMA_CAPS = "flop.runtime-capabilities.v1"
SCHEMA_FINGERPRINT = "flop.runtime-fingerprint.v1"
SCHEMA_JOURNEY = "flop-empires-journey-evidence/v1"
CAPABILITIES = (
    "empire.register", "empire.join", "empire.recon",
    "empire.fortify", "empire.raid", "empire.siege",
    "empire.alliance",
)

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value
def runtime_capabilities(manifest_path: Path, activation_path: Path, launch_path: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    activation = _load(activation_path)
    launched = launch_path.is_file()
    rows = []
    registration_available = {"empire.register", "empire.join"}
    for capability in CAPABILITIES:
        if launched:
            status = "available"
        elif capability in registration_available:
            status = "available"
        else:
            status = "simulation_only"
        rows.append({"id": capability, "status": status})
    return {
        "schema": SCHEMA_CAPS,
        "runtime_id": "flop-empires-season0",
        "season_id": activation.get("season_id"),
        "phase": "ACTIVE" if launched else "REGISTRATION",
        "manifest_hash": sha256(manifest),
        "capabilities": rows,
    }

def runtime_fingerprint(manifest_path: Path, activation_path: Path, revision: str = "unknown") -> dict[str, Any]:
    manifest = _load(manifest_path)
    activation = _load(activation_path)
    body = {
        "product": "flop-empires",
        "season_id": activation.get("season_id"),
        "manifest_hash": sha256(manifest),
        "revision": revision,
        "referee_did": activation.get("referee_did"),
    }
    return {
        "schema": SCHEMA_FINGERPRINT,
        "runtime_id": "flop-empires-season0",
        "fingerprint": body,
        "semantic_digest": sha256(body),
    }

def build_journey_evidence(receipt: Receipt, *, router_receipt: dict[str, Any],
                           capability: str, replay_verified: bool) -> dict[str, Any]:
    if capability not in CAPABILITIES:
        raise ValueError("UNKNOWN_EMPIRES_CAPABILITY")
    if router_receipt.get("schema") != "flop.router-runtime-execution/v1":
        raise ValueError("INVALID_ROUTER_RUNTIME_RECEIPT")
    native = asdict(receipt)
    unsigned = dict(native)
    unsigned.pop("signature", None)
    checks = {
        "native_signature": verify_receipt(receipt),
        "router_request_binding": router_receipt.get("router", {}).get("requestId") == receipt.request_id,
        "runtime_binding": router_receipt.get("runtime", {}).get("targetId") == "flop-empires-season0",
        "replay": bool(replay_verified),
    }
    core = {
        "schema": SCHEMA_JOURNEY,
        "journey_id": "empires_" + sha256({"request_id": receipt.request_id, "event_seq": receipt.event_seq})[:24],
        "capability": capability,
        "actor_did": receipt.actor_did,
        "request_id": receipt.request_id,
        "router_receipt": router_receipt,
        "native_receipt": native,
        "native_receipt_digest": sha256(native),
        "native_unsigned_digest": sha256(unsigned),
        "transition": {"event_seq": receipt.event_seq,
            "state_before_hash": receipt.state_before_hash,
            "state_after_hash": receipt.state_after_hash},
        "verification": checks,
    }
    return {**core, "semantic_digest": sha256(core)}
