from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from .canonical import bytes_, sha256
from .identity import Signer, verify
from .store import Store


PLAYER_ACTIONS=frozenset({
    "claim_yield","fortify","recon","create_attack","submit_defense",
    "raid","siege","create_alliance","set_alliance_active",
})
ACTION_CATEGORY={
    "claim_yield":"ECONOMY","fortify":"DEFENSE","recon":"INTEL",
    "create_attack":"COMBAT","submit_defense":"DEFENSE",
    "raid":"COMBAT","siege":"COMBAT","create_alliance":"DIPLOMACY",
    "set_alliance_active":"DIPLOMACY",
}
CONTRIBUTION_ACTIONS=frozenset({"add_contribution"})


@dataclass(frozen=True)
class MeritPolicy:
    version:str="flop-empires-merit-v1"
    presence_points:int=10
    action_points:tuple[int,...]=(5,3,1)
    counterparty_points:int=2
    counterparty_cap_per_epoch:int=3
    diversity_points:int=2
    diversity_cap:int=5

    def validate(self)->None:
        if self.version!="flop-empires-merit-v1": raise ValueError("unsupported merit policy")
        values=(self.presence_points,self.counterparty_points,self.counterparty_cap_per_epoch,
            self.diversity_points,self.diversity_cap,*self.action_points)
        if any(not isinstance(x,int) or isinstance(x,bool) or x<0 for x in values):
            raise ValueError("merit policy values must be non-negative integers")


def _json_details(row)->dict[str,Any]:
    try:
        value=json.loads(row["details_json"])
        return value if isinstance(value,dict) else {}
    except Exception:
        return {}


def _season_start(store:Store)->int:
    row=store.one("SELECT value FROM config WHERE key='season_started_at'")
    if row: return int(row[0])
    first=store.one("""SELECT accepted_at FROM events
        WHERE accepted=1 AND event_type IN ('activate_season','SEASON_ACTIVATED')
        ORDER BY seq LIMIT 1""")
    if first: return int(first[0])
    first=store.one("SELECT MIN(accepted_at) FROM events WHERE accepted=1")
    return int(first[0] or 0)


def _epoch_of(ts:int,start:int,epoch_seconds:int)->int:
    return max(0,(ts-start)//epoch_seconds)


def _actor_empire(store:Store,did:str)->str|None:
    row=store.one("SELECT empire_id FROM memberships WHERE actor_did=?",(did,))
    return str(row[0]) if row else None


def _counterparties(store:Store,row,details:dict[str,Any],actor_empire:str|None)->set[str]:
    result:set[str]=set()
    attack_id=details.get("attack_id")
    if isinstance(attack_id,str):
        attack=store.one("SELECT attacker_empire_id,defender_empire_id FROM attacks WHERE id=?",(attack_id,))
        if attack:
            for empire in (attack["attacker_empire_id"],attack["defender_empire_id"]):
                if empire and empire!=actor_empire: result.add(str(empire))
    alliance_id=details.get("alliance_id") or details.get("alliance_id_at_creation")
    if isinstance(alliance_id,str):
        for member in store.conn.execute("SELECT empire_id FROM alliance_members WHERE alliance_id=?",(alliance_id,)):
            if member[0]!=actor_empire: result.add(str(member[0]))
    command=details.get("command")
    payload=command.get("payload",{}) if isinstance(command,dict) else {}
    for key in ("counterparty_empire_id","target_empire_id","empire_id"):
        value=payload.get(key) if isinstance(payload,dict) else None
        if isinstance(value,str) and value!=actor_empire: result.add(value)
    return result


def player_metrics(store:Store,did:str,*,epoch_seconds:int=21_600,
                   policy:MeritPolicy|None=None)->dict[str,Any]:
    policy=policy or MeritPolicy(); policy.validate()
    if epoch_seconds<1: raise ValueError("epoch_seconds must be positive")
    empire=_actor_empire(store,did)
    start=_season_start(store)
    per_epoch:dict[int,list[tuple[Any,dict[str,Any]]]]={}
    accepted_actions=0
    category_counts:dict[str,int]={}
    counterparties:set[str]=set()
    for row in store.conn.execute("""SELECT * FROM events
        WHERE actor_did=? AND accepted=1 ORDER BY seq""",(did,)):
        event_type=str(row["event_type"])
        if event_type not in PLAYER_ACTIONS: continue
        details=_json_details(row)
        epoch=_epoch_of(int(row["accepted_at"]),start,epoch_seconds)
        per_epoch.setdefault(epoch,[]).append((row,details))
        accepted_actions+=1
        category=ACTION_CATEGORY.get(event_type,"OTHER")
        category_counts[category]=category_counts.get(category,0)+1
        counterparties.update(_counterparties(store,row,details,empire))

    active_epochs=sorted(per_epoch)
    presence=len(active_epochs)*policy.presence_points
    action_score=0; counterparty_score=0
    for epoch in active_epochs:
        rows=per_epoch[epoch]
        action_score+=sum(policy.action_points[:min(len(rows),len(policy.action_points))])
        epoch_parties:set[str]=set()
        for row,details in rows: epoch_parties.update(_counterparties(store,row,details,empire))
        counterparty_score+=min(len(epoch_parties),policy.counterparty_cap_per_epoch)*policy.counterparty_points
    diversity_score=min(len(category_counts),policy.diversity_cap)*policy.diversity_points
    merit=presence+action_score+counterparty_score+diversity_score
    return {
        "did":did,"empire_id":empire,"active_epochs":len(active_epochs),
        "active_epoch_ids":active_epochs,"accepted_meaningful_actions":accepted_actions,
        "action_categories":dict(sorted(category_counts.items())),
        "unique_counterparties":len(counterparties),
        "score_components":{"presence":presence,"meaningful_actions":action_score,
            "counterparty_diversity":counterparty_score,"strategic_diversity":diversity_score},
        "player_merit":merit,
    }


def contributor_metrics(store:Store,did:str)->dict[str,Any]:
    clusters=list(store.conn.execute("""SELECT id,evidence_class,repository,base_units,verified_at,self_owned
        FROM contribution_clusters WHERE actor_did=? ORDER BY id""",(did,)))
    eligible=[r for r in clusters if not bool(r["self_owned"])]
    repositories=sorted({str(r["repository"]) for r in eligible})
    classes:dict[str,int]={}
    for row in eligible:
        key=str(row["evidence_class"]); classes[key]=classes.get(key,0)+1
    return {
        "verified_contribution_clusters":len(eligible),
        "verified_contribution_units":sum(int(r["base_units"]) for r in eligible),
        "repositories":repositories,
        "evidence_classes":dict(sorted(classes.items())),
        "contributor_merit_basis":"verified_non_self_owned_contribution",
    }


def eligibility_band(metrics:dict[str,Any])->str:
    epochs=int(metrics["active_epochs"]); actions=int(metrics["accepted_meaningful_actions"])
    categories=len(metrics["action_categories"]); parties=int(metrics["unique_counterparties"])
    if epochs>=28 and actions>=40 and categories>=4 and parties>=4: return "VETERAN"
    if epochs>=12 and actions>=20 and categories>=3 and parties>=2: return "CORE"
    if epochs>=4 and actions>=6 and categories>=2: return "ACTIVE"
    if epochs>=1 and actions>=1: return "EXPLORER"
    return "UNQUALIFIED"


def earned_badges(player:dict[str,Any],contributor:dict[str,Any])->list[str]:
    badges=[]
    categories=set(player["action_categories"])
    if player["active_epochs"]>=4: badges.append("SEASON_REGULAR")
    if "INTEL" in categories: badges.append("CARTOGRAPHER")
    if "COMBAT" in categories: badges.append("FIELD_COMMANDER")
    if "DEFENSE" in categories: badges.append("DEFENDER")
    if "DIPLOMACY" in categories: badges.append("DIPLOMAT")
    if player["unique_counterparties"]>=4: badges.append("NETWORKED")
    if len(categories)>=4: badges.append("STRATEGIST")
    if contributor["verified_contribution_clusters"]>0: badges.append("CONTRIBUTOR")
    return badges


def participation_payload(store:Store,did:str,season_id:str,*,epoch_seconds:int=21_600,
                          policy:MeritPolicy|None=None)->dict[str,Any]:
    player=player_metrics(store,did,epoch_seconds=epoch_seconds,policy=policy)
    contributor=contributor_metrics(store,did)
    band=eligibility_band(player)
    last=store.one("SELECT event_hash,seq FROM events ORDER BY seq DESC LIMIT 1")
    payload={
        "type":"flop-empires-participation-v1","season_id":season_id,
        "did":did,"empire_id":player["empire_id"],
        "player":{k:v for k,v in player.items() if k not in {"did","empire_id"}},
        "contributor":contributor,
        "recognition":{"band":band,"badges":earned_badges(player,contributor),
            "early_testnet_eligible":band in {"ACTIVE","CORE","VETERAN"}},
        "testnet_allocation":{"weight":None,"status":"NOT_ASSIGNED",
            "disclaimer":"eligibility evidence only; no token entitlement"},
        "ledger":{"last_event_seq":int(last["seq"]) if last else 0,
            "last_event_hash":str(last["event_hash"]) if last else "0"*64,
            "state_hash":store.state_hash()},
        "merit_policy_version":(policy or MeritPolicy()).version,
    }
    return payload|{"evidence_root":sha256(payload)}


def issue_participation_proof(store:Store,did:str,season_id:str,signer:Signer,*,
                              epoch_seconds:int=21_600,policy:MeritPolicy|None=None)->dict[str,Any]:
    payload=participation_payload(store,did,season_id,epoch_seconds=epoch_seconds,policy=policy)
    body={**payload,"referee_did":signer.did}
    return body|{"signature":signer.sign(bytes_(body))}


def verify_participation_proof(proof:dict[str,Any])->bool:
    if not isinstance(proof,dict) or not isinstance(proof.get("signature"),str): return False
    body=dict(proof); signature=body.pop("signature")
    if body.get("type")!="flop-empires-participation-v1": return False
    root=body.get("evidence_root")
    if not isinstance(root,str): return False
    unsigned=dict(body); unsigned.pop("evidence_root",None); unsigned.pop("referee_did",None)
    if sha256(unsigned)!=root: return False
    did=body.get("referee_did")
    return isinstance(did,str) and verify(did,bytes_(body),signature)
