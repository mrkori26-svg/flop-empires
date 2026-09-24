import json
from flop_empires.identity import EphemeralSigner
from flop_empires.interop import (
    build_journey_evidence, runtime_capabilities, runtime_fingerprint,
)
from flop_empires.receipts import issue_receipt

def _files(tmp_path):
    manifest = tmp_path / "manifest.json"
    activation = tmp_path / "activation.json"
    launch = tmp_path / "launch.json"
    manifest.write_text(json.dumps({"season":"0","rules":"frozen"}), encoding="utf-8")
    activation.write_text(json.dumps({
        "season_id":"season-0",
        "referee_did":"did:key:z6Mk11111111111111111111111111111111111111111111",
    }), encoding="utf-8")
    return manifest, activation, launch

def test_runtime_discovery_is_phase_aware(tmp_path):
    manifest, activation, launch = _files(tmp_path)
    caps = runtime_capabilities(manifest, activation, launch)
    assert caps["schema"] == "flop.runtime-capabilities.v1"
    assert caps["phase"] == "REGISTRATION"
    statuses = {row["id"]: row["status"] for row in caps["capabilities"]}
    assert statuses["empire.recon"] == "simulation_only"
    assert statuses["empire.raid"] == "simulation_only"
    assert statuses["empire.join"] == "available"
def test_fingerprint_is_deterministic(tmp_path):
    manifest, activation, _ = _files(tmp_path)
    a = runtime_fingerprint(manifest, activation, "abc123")
    b = runtime_fingerprint(manifest, activation, "abc123")
    assert a == b
    assert a["runtime_id"] == "flop-empires-season0"
    assert len(a["semantic_digest"]) == 64

def test_journey_binds_router_native_receipt_and_replay():
    signer = EphemeralSigner(bytes(range(32)))
    receipt = issue_receipt(signer, {
        "referee_did": signer.did,
        "request_id": "req-1",
        "actor_did": signer.did,
        "accepted": True,
        "accepted_at": 123,
        "event_seq": 7,
        "state_before_hash": "a" * 64,
        "state_after_hash": "b" * 64,
        "details": {"action": "recon"},
    })
    router = {
        "schema": "flop.router-runtime-execution/v1",
        "receiptId": "runtime_receipt_1",
        "router": {"requestId": "req-1"},
        "runtime": {"targetId": "flop-empires-season0"},
    }
    evidence = build_journey_evidence(
        receipt, router_receipt=router,
        capability="empire.recon", replay_verified=True,
    )
    assert evidence["verification"] == {
        "native_signature": True,
        "router_request_binding": True,
        "runtime_binding": True,
        "replay": True,
    }
    assert evidence["transition"]["state_before_hash"] == "a" * 64
    assert evidence["transition"]["state_after_hash"] == "b" * 64
    assert len(evidence["semantic_digest"]) == 64
