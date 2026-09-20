import json

from flop_empires.events import append_event
from flop_empires.identity import EphemeralSigner
from flop_empires.participation import (
    MeritPolicy,eligibility_band,issue_participation_proof,
    participation_payload,player_metrics,verify_participation_proof,
)
from flop_empires.store import Store


def setup_store():
    store=Store()
    did="did:key:test-player"
    store.conn.execute("INSERT INTO actors VALUES(?,?)",(did,0))
    store.conn.execute("INSERT INTO empires VALUES(?,?,?,?)",("e1","Empire 1","c1",0))
    store.conn.execute("INSERT INTO memberships VALUES(?,?,?)",(did,"e1",0))
    store.conn.execute("INSERT INTO balances VALUES(?,?,?)",("e1",100,0))
    store.conn.execute("INSERT INTO territories VALUES(?,?,?,?)",("c1","e1",1,0))
    store.conn.execute("INSERT INTO config(key,value) VALUES('season_started_at','0')")
    return store,did


def add_event(store,did,seq_time,event_type,details=None):
    before=store.state_hash()
    append_event(store,event_type=event_type,actor_did=did,request_id=f"r-{seq_time}-{event_type}",
        accepted_at=seq_time,accepted=True,command_hash="a"*64,before=before,after=before,
        details=details or {})


def test_diminishing_returns_cap_spam_inside_epoch():
    store,did=setup_store()
    for i in range(8):
        add_event(store,did,10+i,"recon")
    m=player_metrics(store,did,epoch_seconds=100)
    assert m["active_epochs"]==1
    assert m["accepted_meaningful_actions"]==8
    assert m["score_components"]["meaningful_actions"]==9
    assert m["score_components"]["presence"]==10
    assert m["action_categories"]=={"INTEL":8}


def test_sustained_activity_beats_same_epoch_spam():
    spam,did=setup_store()
    for i in range(12): add_event(spam,did,10+i,"recon")
    sustained,did2=setup_store()
    for epoch in range(4): add_event(sustained,did2,epoch*100+1,"recon")
    a=player_metrics(spam,did,epoch_seconds=100)
    b=player_metrics(sustained,did2,epoch_seconds=100)
    assert b["player_merit"]>a["player_merit"]
    assert b["active_epochs"]==4


def test_counterparty_diversity_is_bounded_per_epoch():
    store,did=setup_store()
    for n in range(5):
        defender=f"d{n}"
        store.conn.execute("INSERT INTO empires VALUES(?,?,?,?)",(defender,defender,f"c-{n}",0))
        store.conn.execute("INSERT INTO balances VALUES(?,?,?)",(defender,100,0))
        store.conn.execute("INSERT INTO territories VALUES(?,?,?,?)",(f"c-{n}",defender,1,0))
        store.conn.execute("""INSERT INTO attacks
            (id,kind,attacker_empire_id,defender_empire_id,origin_id,target_id,attack_power,
             allied_defense,alliance_id,created_at,resolved,success,deadline_at,attacker_cost_locked)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (f"a{n}","RAID","e1",defender,"c1",f"c-{n}",10,0,None,1,0,None,100,10))
        add_event(store,did,10+n,"create_attack",{"attack_id":f"a{n}"})
    m=player_metrics(store,did,epoch_seconds=100)
    assert m["unique_counterparties"]==5
    assert m["score_components"]["counterparty_diversity"]==6


def test_contribution_is_separate_from_player_merit():
    store,did=setup_store()
    store.conn.execute("INSERT INTO github_bindings VALUES(?,?,?)",(did,"player",0))
    store.conn.execute("""INSERT INTO contribution_clusters
        (id,empire_id,actor_did,evidence_class,repository,base_units,verified_at,expires_at,self_owned)
        VALUES(?,?,?,?,?,?,?,?,?)""",("c","e1",did,"merged_pull_request","org/repo",50,1,999,0))
    payload=participation_payload(store,did,"season-x",epoch_seconds=100)
    assert payload["player"]["player_merit"]==0
    assert payload["contributor"]["verified_contribution_units"]==50
    assert "CONTRIBUTOR" in payload["recognition"]["badges"]
    assert payload["testnet_allocation"]["status"]=="NOT_ASSIGNED"


def test_band_requires_sustained_and_diverse_activity():
    metrics={"active_epochs":12,"accepted_meaningful_actions":20,
        "action_categories":{"INTEL":1,"COMBAT":1,"DEFENSE":1},
        "unique_counterparties":2}
    assert eligibility_band(metrics)=="CORE"
    metrics["unique_counterparties"]=1
    assert eligibility_band(metrics)=="ACTIVE"


def test_signed_proof_verifies_and_tampering_fails():
    store,did=setup_store()
    for epoch in range(4):
        add_event(store,did,epoch*100+1,"recon")
        add_event(store,did,epoch*100+2,"fortify")
    signer=EphemeralSigner(b"z"*32)
    proof=issue_participation_proof(store,did,"season-x",signer,epoch_seconds=100)
    assert proof["recognition"]["band"]=="ACTIVE"
    assert proof["recognition"]["early_testnet_eligible"] is True
    assert verify_participation_proof(proof)
    tampered=json.loads(json.dumps(proof))
    tampered["player"]["player_merit"]+=1
    assert not verify_participation_proof(tampered)


def test_unqualified_has_no_early_testnet_flag():
    store,did=setup_store()
    payload=participation_payload(store,did,"season-x",epoch_seconds=100)
    assert payload["recognition"]["band"]=="UNQUALIFIED"
    assert payload["recognition"]["early_testnet_eligible"] is False
