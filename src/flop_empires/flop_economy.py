from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import json

from .canonical import sha256
from .store import Store


OPERATIONS=frozenset({"PAY","TRANSFER","LOCK","STAKE","REWARD","TREASURY"})


@dataclass(frozen=True)
class FlopEconomyConfig:
    version:str="flop-token-economy-v0.1"
    chain_id:int=0
    token_address:str=""
    decimals:int=18
    epoch_seconds:int=21_600
    faucet_per_epoch:int=20
    faucet_balance_cap:int=120
    protocol_fee_bp:int=0
    treasury_empire_id:str="__protocol_treasury__"

    def validate(self)->None:
        if self.version!="flop-token-economy-v0.1": raise ValueError("unsupported FLOP economy version")
        if self.chain_id<0 or self.decimals<0 or self.epoch_seconds<1: raise ValueError("invalid chain/economy parameters")
        if min(self.faucet_per_epoch,self.faucet_balance_cap,self.protocol_fee_bp)<0: raise ValueError("negative parameter")
        if self.protocol_fee_bp>10_000: raise ValueError("protocol_fee_bp out of range")


@dataclass(frozen=True)
class SessionPolicy:
    max_per_action:int
    max_per_epoch:int
    allowed_operations:tuple[str,...]
    expires_at:int

    def validate(self)->None:
        if self.max_per_action<0 or self.max_per_epoch<0 or self.expires_at<0: raise ValueError("invalid session policy")
        unknown=set(self.allowed_operations)-OPERATIONS
        if unknown: raise ValueError(f"unsupported session operations: {sorted(unknown)}")

    def permits(self,operation:str,amount:int,now:int,spent_this_epoch:int)->bool:
        self.validate()
        return (operation in self.allowed_operations and 0<=amount<=self.max_per_action
            and spent_this_epoch+amount<=self.max_per_epoch and now<=self.expires_at)


class FlopLedger:
    def __init__(self,store:Store,config:FlopEconomyConfig):
        config.validate(); self.store=store; self.config=config
        prior=store.one("SELECT value FROM config WHERE key='flop_economy_version'")
        if prior and prior[0]!=config.version: raise RuntimeError("FLOP economy version mismatch")
        store.conn.execute("INSERT OR IGNORE INTO config(key,value) VALUES('flop_economy_version',?)",(config.version,))
        store.conn.execute("INSERT OR IGNORE INTO config(key,value) VALUES('flop_economy_config_hash',?)",(sha256(asdict(config)),))
        existing=store.one("SELECT value FROM config WHERE key='flop_economy_config_hash'")[0]
        if existing!=sha256(asdict(config)): raise RuntimeError("FLOP economy config mismatch")

    def ensure_account(self,empire_id:str,initial:int=0)->None:
        if initial<0: raise ValueError("negative initial balance")
        self.store.conn.execute("INSERT OR IGNORE INTO flop_accounts(empire_id,available,locked,last_faucet_epoch) VALUES(?,?,0,-1)",
            (empire_id,initial))

    def account(self,empire_id:str)->dict[str,int]:
        row=self.store.one("SELECT available,locked,last_faucet_epoch FROM flop_accounts WHERE empire_id=?",(empire_id,))
        if not row: raise ValueError("unknown FLOP account")
        return dict(row)

    def faucet(self,empire_id:str,epoch:int)->int:
        if epoch<0: raise ValueError("invalid epoch")
        self.ensure_account(empire_id)
        row=self.account(empire_id)
        if row["last_faucet_epoch"]>=epoch: return 0
        grant=min(self.config.faucet_per_epoch,max(0,self.config.faucet_balance_cap-row["available"]))
        self.store.conn.execute("UPDATE flop_accounts SET available=available+?,last_faucet_epoch=? WHERE empire_id=?",
            (grant,epoch,empire_id))
        return grant

    def quote(self,*,quote_id:str,actor_did:str,empire_id:str,operation:str,amount:int,
              now:int,expires_at:int,counterparty_empire_id:str|None=None,payload:dict[str,Any]|None=None)->dict[str,Any]:
        if operation not in OPERATIONS: raise ValueError("unsupported operation")
        if amount<0 or expires_at<now: raise ValueError("invalid quote")
        self.ensure_account(empire_id)
        body={"quote_id":quote_id,"actor_did":actor_did,"empire_id":empire_id,"operation":operation,
            "amount":amount,"counterparty_empire_id":counterparty_empire_id,"expires_at":expires_at,
            "payload":payload or {}}
        payload_hash=sha256(body)
        self.store.conn.execute("""INSERT INTO flop_quotes
            (quote_id,actor_did,empire_id,operation,amount,counterparty_empire_id,expires_at,payload_hash,status)
            VALUES(?,?,?,?,?,?,?,?, 'OPEN')""",
            (quote_id,actor_did,empire_id,operation,amount,counterparty_empire_id,expires_at,payload_hash))
        return body|{"payload_hash":payload_hash}

    def spent_in_epoch(self,empire_id:str,epoch:int)->int:
        row=self.store.one("""SELECT COALESCE(SUM(amount),0) FROM flop_movements
            WHERE from_empire_id=? AND epoch=? AND status='SETTLED'""",(empire_id,epoch))
        return int(row[0])

    def execute_quote(self,quote_id:str,*,now:int,epoch:int,settlement_ref:str,
                      policy:SessionPolicy|None=None,lock_id:str|None=None)->dict[str,Any]:
        q=self.store.one("SELECT * FROM flop_quotes WHERE quote_id=?",(quote_id,))
        if not q: raise ValueError("unknown quote")
        if q["status"]!="OPEN": raise ValueError("quote is not open")
        if now>q["expires_at"]: raise ValueError("quote expired")
        op=q["operation"]; amount=int(q["amount"]); src=q["empire_id"]; dst=q["counterparty_empire_id"]
        if policy and not policy.permits(op,amount,now,self.spent_in_epoch(src,epoch)): raise PermissionError("session policy denied")
        self.ensure_account(src)
        if dst: self.ensure_account(dst)
        if op in {"PAY","TRANSFER","LOCK","STAKE","TREASURY"} and self.account(src)["available"]<amount:
            raise ValueError("insufficient FLOP")
        movement_id=sha256({"quote_id":quote_id,"settlement_ref":settlement_ref,"operation":op})[:32]
        with self.store.transaction():
            if op=="TRANSFER":
                if not dst: raise ValueError("transfer requires counterparty")
                self._debit(src,amount); self._credit(dst,amount)
            elif op in {"PAY","TREASURY"}:
                self._debit(src,amount); self.ensure_account(self.config.treasury_empire_id); self._credit(self.config.treasury_empire_id,amount)
                dst=self.config.treasury_empire_id
            elif op in {"LOCK","STAKE"}:
                lid=lock_id or f"lock-{quote_id}"
                self._debit(src,amount,lock=True)
                self.store.conn.execute("""INSERT INTO flop_locks
                    (lock_id,empire_id,amount,purpose,status,counterparty_empire_id,expires_at,settlement_ref)
                    VALUES(?,?,?,?, 'LOCKED',?,?,?)""",(lid,src,amount,op,dst,q["expires_at"],settlement_ref))
            elif op=="REWARD":
                self.ensure_account(self.config.treasury_empire_id)
                if self.account(self.config.treasury_empire_id)["available"]<amount: raise ValueError("treasury has insufficient FLOP")
                self._debit(self.config.treasury_empire_id,amount); self._credit(src,amount)
                dst=src; src=self.config.treasury_empire_id
            self.store.conn.execute("""INSERT INTO flop_movements
                (movement_id,quote_id,kind,from_empire_id,to_empire_id,amount,epoch,settlement_ref,status,created_at)
                VALUES(?,?,?,?,?,?,?,?, 'SETTLED',?)""",(movement_id,quote_id,op,src,dst,amount,epoch,settlement_ref,now))
            self.store.conn.execute("UPDATE flop_quotes SET status='EXECUTED' WHERE quote_id=?",(quote_id,))
        return {"movement_id":movement_id,"quote_id":quote_id,"operation":op,"amount":amount,
            "from_empire_id":src,"to_empire_id":dst,"settlement_ref":settlement_ref}

    def resolve_lock(self,lock_id:str,*,outcome:str,now:int,settlement_ref:str)->dict[str,Any]:
        row=self.store.one("SELECT * FROM flop_locks WHERE lock_id=?",(lock_id,))
        if not row or row["status"]!="LOCKED": raise ValueError("lock not active")
        if outcome not in {"RETURN","SLASH","RELEASE_TO_COUNTERPARTY"}: raise ValueError("invalid lock outcome")
        owner=row["empire_id"]; amount=int(row["amount"]); cp=row["counterparty_empire_id"]
        with self.store.transaction():
            self.store.conn.execute("UPDATE flop_accounts SET locked=locked-? WHERE empire_id=?",(amount,owner))
            target=owner
            if outcome=="SLASH":
                target=self.config.treasury_empire_id; self.ensure_account(target); self._credit(target,amount)
            elif outcome=="RELEASE_TO_COUNTERPARTY":
                if not cp: raise ValueError("counterparty required")
                target=cp; self.ensure_account(target); self._credit(target,amount)
            else:
                self._credit(owner,amount)
            self.store.conn.execute("UPDATE flop_locks SET status=?,settlement_ref=? WHERE lock_id=?",(outcome,settlement_ref,lock_id))
        return {"lock_id":lock_id,"outcome":outcome,"amount":amount,"recipient":target,"settlement_ref":settlement_ref,"resolved_at":now}

    def _debit(self,empire_id:str,amount:int,*,lock:bool=False)->None:
        self.store.conn.execute("UPDATE flop_accounts SET available=available-?,locked=locked+? WHERE empire_id=?",
            (amount,amount if lock else 0,empire_id))

    def _credit(self,empire_id:str,amount:int)->None:
        self.store.conn.execute("UPDATE flop_accounts SET available=available+? WHERE empire_id=?",(amount,empire_id))
