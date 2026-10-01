from __future__ import annotations

import json
import msvcrt
import os
import time
from pathlib import Path

import httpx

from .identity import ExternalRefereeSigner
from .manifest import SeasonZeroFreezeV2CandidateManifest
from .recovery import RecoveryRecord
from .launch import LaunchAuthorization
from .world_bootstrap import bootstrap_frozen_world
from .models import SeasonStatus
from .production import ProductionRuntime
from .production_cli import load_external_backend, load_verified
from .store import Store
from .final_artifact import build_final_artifact, write_final_artifact

POLL_SECONDS=15
ROOT=Path(__file__).resolve().parents[2]
RUNTIME_DIR=Path(os.environ["LOCALAPPDATA"])/"FLOPEmpires"/"season0-runtime-v1"
DB_PATH=RUNTIME_DIR/"season0.sqlite3"
STATUS_PATH=RUNTIME_DIR/"runner-status.json"
LOCK_PATH=RUNTIME_DIR/"runner.lock"
MANIFEST_PATH=ROOT/"season/SEASON-0-MANIFEST-FREEZE-V2-CANDIDATE.json"
ACTIVATION_PATH=ROOT/"season/SEASON-0-ACTIVATION-v1.json"
RECOVERY_PATH=ROOT/"season/SEASON-0-RECOVERY-v1.json"
LAUNCH_PATH=ROOT/"season/SEASON-0-LAUNCH-AUTHORIZATION-v1.json"
WORLD_PATH=ROOT/"season/world-season-0-v1.json"
BACKEND="flop_empires.windows_signer:season0_referee_backend"
FINAL_ARTIFACT_PATH=RUNTIME_DIR/"season0-final-state-v1.json"
WORLD_PATH=ROOT/"season/world-season-0-v1.json"


def _priority() -> None:
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x00004000)
    except Exception:
        pass

def _atomic_status(value: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True,exist_ok=True)
    temporary=STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,sort_keys=True,separators=(",",":")),encoding="utf-8")
    os.replace(temporary,STATUS_PATH)


def _singleton():
    RUNTIME_DIR.mkdir(parents=True,exist_ok=True)
    handle=LOCK_PATH.open("a+b")
    if handle.tell()==0:
        handle.write(b"0");handle.flush()
    handle.seek(0)
    try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        print("SEASON0_RUNNER_ALREADY_ACTIVE")
        raise SystemExit(0)
    return handle

def _autonomous_referee(runtime: ProductionRuntime) -> dict:
    settled=resolved=0
    status=runtime.engine.advance_production_lifecycle()
    if status!=SeasonStatus.ACTIVE:
        return {"status":status,"settled_epochs":0,"resolved_attacks":0}
    now=int(runtime.engine.clock()); game_now=runtime.engine._game_now(now)
    started=runtime.store.one("SELECT value FROM config WHERE key='season_started_at'")
    if started:
        max_epoch=min(runtime.manifest.value["intended_duration_epochs"]-1,
            max(-1,(game_now-int(started[0]))//runtime.manifest.value["epoch_duration"]))
        rows=list(runtime.store.conn.execute("SELECT last_settled_epoch FROM empire_economy"))
        last=min((row[0] for row in rows),default=max_epoch)
        for epoch in range(last+1,max_epoch+1):
            runtime.engine.execute({"action":"settle_epoch","actor_did":runtime.binding.context.referee_did,
                "request_id":f"auto-settle-epoch-{epoch}","payload":{"epoch":epoch}})
            settled+=1
    due=list(runtime.store.conn.execute("SELECT id FROM attacks WHERE resolved=0 AND deadline_at<=? ORDER BY id",(game_now,)))
    for row in due:
        attack_id=row[0]
        runtime.engine.execute({"action":"resolve_attack","actor_did":runtime.binding.context.referee_did,
            "request_id":f"auto-resolve-{attack_id}","payload":{"attack_id":attack_id}})
        resolved+=1
    return {"status":status,"settled_epochs":settled,"resolved_attacks":resolved}

def _cycle(client: httpx.Client) -> dict:
    manifest=SeasonZeroFreezeV2CandidateManifest.load(MANIFEST_PATH)
    backend=load_external_backend(BACKEND)
    signer=ExternalRefereeSigner(manifest.referee_did,backend)
    store=Store(DB_PATH)
    if store.one("SELECT COUNT(*) FROM territories")[0]==0:
        bootstrap_frozen_world(store,WORLD_PATH,expected_hash=manifest.world_graph_hash,
            initial_balances=manifest.initial_balances,now=int(time.time()))
    launch=None
    if RECOVERY_PATH.is_file():
        recovery=RecoveryRecord.load(RECOVERY_PATH,manifest)
        if LAUNCH_PATH.is_file(): launch=LaunchAuthorization.load(LAUNCH_PATH,manifest,recovery.context())
        runtime=ProductionRuntime.from_verified_recovery(manifest,recovery,store,signer,client,launch=launch)
    else:
        activation=__import__('flop_empires.activation',fromlist=['ActivationRecord']).ActivationRecord.load(ACTIVATION_PATH,manifest)
        if LAUNCH_PATH.is_file(): launch=LaunchAuthorization.load(LAUNCH_PATH,manifest,activation.context())
        runtime=ProductionRuntime.from_verified_activation(manifest,activation,None,store,signer,client,launch=launch)
    status=runtime.engine.advance_production_lifecycle()
    receipts=[]
    if status!=SeasonStatus.FINALIZED:
        receipts=runtime.ingestor.poll(runtime.actions)
    auto=_autonomous_referee(runtime)
    recovered=runtime.outbox.recover()
    flushed=runtime.outbox.flush(runtime.events)
    final_artifact=False
    if auto["status"]==SeasonStatus.FINALIZED:
        write_final_artifact(build_final_artifact(store,MANIFEST_PATH,ACTIVATION_PATH,WORLD_PATH,RECOVERY_PATH,LAUNCH_PATH),FINAL_ARTIFACT_PATH); final_artifact=True
    return {"status":auto["status"],"receipts":len(receipts),"recovered":recovered,
        "published":flushed["published"],"pending":flushed["pending"],
        "settled_epochs":auto["settled_epochs"],"resolved_attacks":auto["resolved_attacks"],
        "final_artifact":final_artifact,"launch_authorized":launch is not None}


def main() -> int:
    _priority();lock=_singleton();failures=0
    with httpx.Client(timeout=10.0) as client:
        while True:
            started=int(time.time())
            try:
                result=_cycle(client);failures=0
                _atomic_status({"runner":"RUNNING","pid":os.getpid(),"heartbeat":int(time.time()),**result})
            except Exception as exc:
                failures+=1
                _atomic_status({"runner":"ERROR_RETRYING","pid":os.getpid(),"heartbeat":int(time.time()),
                    "failures":failures,"error_type":type(exc).__name__,"safe_error":str(exc)[:160]})
            time.sleep(max(1,POLL_SECONDS-(int(time.time())-started)))
    lock.close();return 0


if __name__=="__main__":
    raise SystemExit(main())
