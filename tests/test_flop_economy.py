import pytest

from flop_empires.flop_economy import FlopEconomyConfig,FlopLedger,SessionPolicy
from flop_empires.store import Store


def ledger(**kwargs):
    store=Store()
    cfg=FlopEconomyConfig(chain_id=10143,token_address="0xTEST",**kwargs)
    return store,FlopLedger(store,cfg)


def test_faucet_is_epoch_limited_and_balance_capped():
    store,l=ledger(faucet_per_epoch=20,faucet_balance_cap=50)
    assert l.faucet("a",0)==20
    assert l.faucet("a",0)==0
    assert l.faucet("a",1)==20
    assert l.faucet("a",2)==10
    assert l.faucet("a",3)==0
    assert l.account("a")["available"]==50


def test_transfer_is_quote_bound_and_settlement_referenced():
    store,l=ledger()
    l.ensure_account("a",100); l.ensure_account("b",0)
    q=l.quote(quote_id="q1",actor_did="did:key:a",empire_id="a",operation="TRANSFER",
        amount=15,now=10,expires_at=20,counterparty_empire_id="b",payload={"reason":"intel"})
    assert len(q["payload_hash"])==64
    move=l.execute_quote("q1",now=11,epoch=0,settlement_ref="tx:test:1")
    assert move["settlement_ref"]=="tx:test:1"
    assert l.account("a")["available"]==85
    assert l.account("b")["available"]==15
    with pytest.raises(ValueError): l.execute_quote("q1",now=12,epoch=0,settlement_ref="tx:test:2")


def test_stake_can_be_slashed_to_protocol_treasury():
    store,l=ledger()
    l.ensure_account("a",100)
    l.quote(quote_id="nap",actor_did="did:key:a",empire_id="a",operation="STAKE",
        amount=25,now=1,expires_at=100,counterparty_empire_id="b")
    l.execute_quote("nap",now=2,epoch=0,settlement_ref="lock:test",lock_id="nap-a")
    assert l.account("a")=={"available":75,"locked":25,"last_faucet_epoch":-1}
    result=l.resolve_lock("nap-a",outcome="SLASH",now=3,settlement_ref="slash:test")
    assert result["recipient"]=="__protocol_treasury__"
    assert l.account("a")["locked"]==0
    assert l.account("__protocol_treasury__")["available"]==25


def test_session_policy_caps_action_and_epoch_spend():
    store,l=ledger()
    l.ensure_account("a",100); l.ensure_account("b",0)
    p=SessionPolicy(max_per_action=10,max_per_epoch=15,allowed_operations=("TRANSFER","PAY"),expires_at=100)
    l.quote(quote_id="one",actor_did="did:key:a",empire_id="a",operation="TRANSFER",amount=10,
        now=1,expires_at=10,counterparty_empire_id="b")
    l.execute_quote("one",now=2,epoch=0,settlement_ref="tx:1",policy=p)
    l.quote(quote_id="two",actor_did="did:key:a",empire_id="a",operation="TRANSFER",amount=6,
        now=3,expires_at=10,counterparty_empire_id="b")
    with pytest.raises(PermissionError):
        l.execute_quote("two",now=4,epoch=0,settlement_ref="tx:2",policy=p)


def test_expired_quote_cannot_execute():
    _,l=ledger(); l.ensure_account("a",10)
    l.quote(quote_id="q",actor_did="did:key:a",empire_id="a",operation="PAY",amount=1,now=1,expires_at=2)
    with pytest.raises(ValueError,match="expired"):
        l.execute_quote("q",now=3,epoch=0,settlement_ref="tx:x")


def test_flop_tables_do_not_enter_state_projection_until_economy_is_enabled():
    store=Store()
    before=store.state()
    assert "flop_accounts" not in before
    FlopLedger(store,FlopEconomyConfig(chain_id=10143,token_address="0xTEST"))
    after=store.state()
    assert "flop_accounts" in after and "flop_quotes" in after
