import argparse
import json
from pathlib import Path
from flop_empires.identity import EphemeralSigner
from flop_empires.interop import build_journey_evidence
from flop_empires.receipts import issue_receipt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    signer = EphemeralSigner(bytes(range(32)))
    receipt = issue_receipt(signer, {
        "referee_did": signer.did,
        "request_id": "interop-recon-001",
        "actor_did": signer.did,
        "accepted": True,
        "accepted_at": 1,
        "event_seq": 1,
        "state_before_hash": "a" * 64,
        "state_after_hash": "b" * 64,
        "details": {"mode":"simulation","action":"recon"},
    })
    router = {
        "schema":"flop.router-runtime-execution/v1",
        "receiptId":"runtime_receipt_interop_demo",
        "router":{"requestId":"interop-recon-001"},
        "runtime":{"targetId":"flop-empires-season0"},
    }
    evidence = build_journey_evidence(
        receipt, router_receipt=router,
        capability="empire.recon", replay_verified=True,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
