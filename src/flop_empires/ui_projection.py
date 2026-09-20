from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from .participation import participation_payload
from .store import Store

EMPIRE_PALETTE = [
    "#7c3aed", "#2563eb", "#0891b2", "#059669",
    "#65a30d", "#ca8a04", "#ea580c", "#dc2626",
    "#db2777", "#9333ea", "#4f46e5", "#0284c7",
    "#0d9488", "#16a34a", "#84cc16", "#d97706",
]

REGION_CENTERS = [
    (175, 215), (365, 160), (565, 170), (735, 245),
    (725, 600), (540, 720), (325, 715), (155, 610),
]


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args)]


def _layout(index: int) -> tuple[float, float]:
    region = index // 8
    local = index % 8
    cx, cy = REGION_CENTERS[region]
    angle = -math.pi / 2 + local * math.pi / 4
    radius = 58 + (12 if local % 2 else 0)
    x = cx + math.cos(angle) * radius
    y = cy + math.sin(angle) * radius
    return round(x, 2), round(y, 2)


def build_public_state(db_path: str | Path, world_path: str | Path, activation_path: str | Path, viewer_did: str | None = None) -> dict[str, Any]:
    world = _read_json(world_path)
    activation = _read_json(activation_path)
    recovery=None
    recovery_path=Path(activation_path).with_name("SEASON-0-RECOVERY-v1.json")
    if recovery_path.is_file():
        r=_read_json(recovery_path); recovery=r
        activation={**activation,"activation_id":r["recovery_id"],"registration_open":r["registration_open"],
            "registration_close":r["registration_close"],"season_start":r["season_start"],"season_end":r["season_end"],
            "actions_namespace":r["duplex_namespace"],"events_namespace":r["duplex_namespace"]}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        config = dict(conn.execute("SELECT key,value FROM config"))
        live_territories = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM territories")}
        empires = _rows(conn, "SELECT * FROM empires ORDER BY id")
        economy = {r["empire_id"]: dict(r) for r in conn.execute("SELECT empire_id,prestige FROM empire_economy")}
        attacks = _rows(conn, "SELECT * FROM attacks ORDER BY created_at DESC")
        events = _rows(conn, "SELECT seq,event_type,request_id,accepted_at,accepted FROM events ORDER BY seq DESC LIMIT 40")
        memberships = _rows(conn, "SELECT * FROM memberships ORDER BY empire_id,actor_did")
        actor_count = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        event_head = conn.execute("SELECT seq,event_hash,state_after_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        alliances = _rows(conn, "SELECT * FROM alliances ORDER BY id")
        alliance_members = _rows(conn, "SELECT * FROM alliance_members ORDER BY alliance_id,empire_id")
        defenses = _rows(conn, "SELECT * FROM attack_defenses ORDER BY attack_id,empire_id")
        balances = {r["empire_id"]: dict(r) for r in conn.execute("SELECT * FROM balances")}
        viewer_registered = bool(conn.execute("SELECT 1 FROM actors WHERE did=?", (viewer_did,)).fetchone()) if viewer_did else False
        viewer_registered = bool(conn.execute("SELECT 1 FROM actors WHERE did=?", (viewer_did,)).fetchone()) if viewer_did else False
        viewer_empire_row = conn.execute("SELECT empire_id FROM memberships WHERE actor_did=?", (viewer_did,)).fetchone() if viewer_did else None
        viewer_empire = viewer_empire_row[0] if viewer_empire_row else None
        viewer_economy_row = conn.execute("SELECT * FROM empire_economy WHERE empire_id=?", (viewer_empire,)).fetchone() if viewer_empire else None
        viewer_economy = dict(viewer_economy_row) if viewer_economy_row else None
        viewer_balance = balances.get(viewer_empire) if viewer_empire else None
        viewer_events = _rows(conn, "SELECT seq,event_type,accepted_at,details_json FROM events WHERE actor_did=? AND accepted=1 ORDER BY seq DESC LIMIT 80", (viewer_did,)) if viewer_did else []
    finally:
        conn.close()

    empire_ids = [f"season0-e{i:02d}" for i in range(1, 17)]
    live_by_id = {e["id"]: e for e in empires}
    member_count: dict[str, int] = {}
    member_dids: dict[str, list[str]] = {}
    for row in memberships:
        member_count[row["empire_id"]] = member_count.get(row["empire_id"], 0) + 1
        member_dids.setdefault(row["empire_id"], []).append(row["actor_did"])

    merit_by_empire: dict[str, dict[str, Any]] = {}
    merit_store=Store(db_path,readonly=True)
    try:
        for empire_id,dids in member_dids.items():
            proofs=[participation_payload(merit_store,did,activation["season_id"],epoch_seconds=21_600) for did in dids]
            if not proofs: continue
            merit_by_empire[empire_id]={
                "player_merit":sum(int(p["player"]["player_merit"]) for p in proofs),
                "active_epochs":len(set().union(*(set(p["player"]["active_epoch_ids"]) for p in proofs))),
                "band":max((p["recognition"]["band"] for p in proofs),
                    key=lambda x:{"UNQUALIFIED":0,"EXPLORER":1,"ACTIVE":2,"CORE":3,"VETERAN":4}.get(x,0)),
                "badges":sorted(set().union(*(set(p["recognition"]["badges"]) for p in proofs))),
                "early_testnet_eligible":any(bool(p["recognition"]["early_testnet_eligible"]) for p in proofs),
            }
    finally:
        merit_store.close()

    empire_view = []
    for i, empire_id in enumerate(empire_ids):
        live = live_by_id.get(empire_id, {})
        econ = economy.get(empire_id, {})
        empire_view.append({
            "id": empire_id,
            "name": live.get("name") or f"Empire {i + 1:02d}",
            "color": EMPIRE_PALETTE[i],
            "claimed": member_count.get(empire_id, 0) > 0,
            "members": member_count.get(empire_id, 0),
            "standing": None,
            "standing_state": "PENDING_RUNTIME_MATERIALIZATION",
            "prestige_public": int(econ.get("prestige", 0) or 0),
            "participation": merit_by_empire.get(empire_id, {
                "player_merit":0,"active_epochs":0,"band":"UNQUALIFIED",
                "badges":[],"early_testnet_eligible":False,
            }),
        })

    empire_lookup = {e["id"]: e for e in empire_view}
    territories = []
    for index, frozen in enumerate(world["territories"]):
        live = live_territories.get(frozen["id"])
        owner = live["owner_empire_id"] if live else frozen["owner"]
        x, y = _layout(index)
        item = {
            "id": frozen["id"],
            "index": index,
            "region": frozen["region"],
            "owner": owner,
            "owner_name": empire_lookup.get(owner, {}).get("name", owner),
            "color": empire_lookup.get(owner, {}).get("color", "#64748b"),
            "capital": bool(live["is_capital"] if live else frozen["capital"]),
            "strategic_value": int(frozen.get("strategic_value", 1)),
            "fog": {"fortification": "HIDDEN", "production": "HIDDEN"},
            "x": x,
            "y": y,
            "live": live is not None,
        }
        if viewer_empire and owner == viewer_empire and live:
            item["private"] = {"fortification": int(live["fortification"]), "production": frozen.get("base_production", {})}
        territories.append(item)

    public_events = [{
        "seq": e["seq"],
        "event_type": e["event_type"],
        "request_id": e["request_id"],
        "accepted_at": e["accepted_at"],
        "accepted": bool(e["accepted"]),
    } for e in events]
    defense_by_attack = {}
    for row in defenses: defense_by_attack.setdefault(row["attack_id"], []).append(row)
    active_attacks = [{k: a.get(k) for k in (
        "id", "kind", "attacker_empire_id", "defender_empire_id", "origin_id",
        "target_id", "alliance_id", "created_at", "deadline_at", "resolved", "success"
    )} | {"defense_submissions": len(defense_by_attack.get(a["id"], []))} for a in attacks if not a["resolved"]]
    recon_intel = []
    for e in viewer_events:
        if e["event_type"] != "recon": continue
        d=json.loads(e["details_json"]); expires=d.get("expires_at")
        if expires and expires >= int(__import__("time").time()): recon_intel.append({k:d.get(k) for k in ("territory_id","owner_empire_id","is_capital","fortification","expires_at")})

    return {
        "season": {
            "id": activation["season_id"],
            "status": config.get("season_status", "UNKNOWN"),
            "registration_open": activation["registration_open"],
            "registration_close": activation["registration_close"],
            "season_start": activation["season_start"],
            "season_end": activation["season_end"],
            "activation_id": activation["activation_id"],
            "manifest_hash": activation["frozen_manifest_hash"],
            "actions_namespace": activation["actions_namespace"],
            "events_namespace": activation["events_namespace"],
            "recovery": ({
                "active": True,
                "version": recovery["version"],
                "recovery_id": recovery["recovery_id"],
                "original_activation_id": recovery["original_activation_id"],
                "reason_codes": recovery["reason_codes"],
                "failed_state_hash": recovery["failed_state_hash"],
                "duplex_namespace": recovery["duplex_namespace"],
                "evidence_url": "https://github.com/retardio73-boop/flop-empires/blob/main/reports/season-0-recovery-evidence-v1.md",
            } if recovery else None),
        },
        "world": {
            "schema": world["schema"],
            "seed": world["seed"],
            "layout": "regional-v2",
            "empires": empire_view,
            "territories": territories,
            "edges": world["edges"],
            "live_materialized": len(live_territories) == len(world["territories"]),
        },
        "activity": {
            "active_attacks": active_attacks,
            "recent_events": public_events,
            "active_alliances": [a for a in alliances if a["active"]],
            "alliances": alliances,
            "alliance_members": alliance_members,
        },
        "registration": {
            "actors": actor_count,
            "memberships_by_empire": member_count,
        },
        "viewer": {
            "authenticated": bool(viewer_did),
            "registered": viewer_registered,
            "did": viewer_did,
            "registered": viewer_registered,
            "empire_id": viewer_empire,
            "economy": viewer_economy,
            "balance": viewer_balance,
            "recon_intel": recon_intel,
            "incoming_attacks": [a for a in active_attacks if viewer_empire and a["defender_empire_id"] == viewer_empire],
            "outgoing_attacks": [a for a in active_attacks if viewer_empire and a["attacker_empire_id"] == viewer_empire],
            "alliances": [a for a in alliances if viewer_empire and any(m["alliance_id"]==a["id"] and m["empire_id"]==viewer_empire for m in alliance_members)],
            "action_context": {"season_active": config.get("season_status") == "ACTIVE", "unlocked_engineering": int(viewer_balance["available"]) if viewer_balance else 0},
        },
        "capabilities": {
            "fog_safe_public_projection": True,
            "viewer_highlight_without_private_reveal": True,
            "signed_private_view": True,
            "raid_siege": True,
            "recon": True,
            "alliances_runtime": True,
            "treaties_rule_contract": True,
            "treaties_runtime_materialized": False,
            "trade_rule_contract": True,
            "trade_runtime_materialized": False,
            "standing_mode": "relative_rank",
            "standing_runtime_materialized": False,
            "victory_scoring": "world-share-normalized",
        },
        "evidence": {
            "projection_schema": "flop-empires-public-state-v1",
            "manifest_hash": activation["frozen_manifest_hash"],
            "world_hash": config.get("world_graph_hash"),
            "event_count": event_count,
            "event_head_seq": int(event_head["seq"]) if event_head else None,
            "event_head_hash": event_head["event_hash"] if event_head else None,
            "state_after_hash": event_head["state_after_hash"] if event_head else None,
            "claim": "Public view is fog-safe and derived read-only from the frozen world plus canonical SQLite state.",
        },
    }
