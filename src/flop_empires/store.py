from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .canonical import sha256

MIGRATIONS = [
"""
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actors(did TEXT PRIMARY KEY, registered_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS empires(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, capital_id TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(actor_did TEXT PRIMARY KEY REFERENCES actors(did), empire_id TEXT NOT NULL REFERENCES empires(id), joined_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS github_bindings(actor_did TEXT PRIMARY KEY REFERENCES actors(did), login TEXT NOT NULL UNIQUE, verified_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS contribution_clusters(id TEXT PRIMARY KEY, empire_id TEXT NOT NULL REFERENCES empires(id), actor_did TEXT NOT NULL REFERENCES actors(did), evidence_class TEXT NOT NULL, repository TEXT NOT NULL, base_units INTEGER NOT NULL CHECK(base_units>=0), verified_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, self_owned INTEGER NOT NULL CHECK(self_owned IN(0,1)));
CREATE TABLE IF NOT EXISTS contribution_evidence(url TEXT PRIMARY KEY, cluster_id TEXT NOT NULL REFERENCES contribution_clusters(id), verified INTEGER NOT NULL CHECK(verified IN(0,1)));
CREATE TABLE IF NOT EXISTS balances(empire_id TEXT PRIMARY KEY REFERENCES empires(id), available INTEGER NOT NULL DEFAULT 0 CHECK(available>=0), locked INTEGER NOT NULL DEFAULT 0 CHECK(locked>=0));
CREATE TABLE IF NOT EXISTS territories(id TEXT PRIMARY KEY, owner_empire_id TEXT NOT NULL REFERENCES empires(id), is_capital INTEGER NOT NULL DEFAULT 0 CHECK(is_capital IN(0,1)), fortification INTEGER NOT NULL DEFAULT 0 CHECK(fortification>=0));
CREATE TABLE IF NOT EXISTS territory_edges(a TEXT NOT NULL REFERENCES territories(id), b TEXT NOT NULL REFERENCES territories(id), PRIMARY KEY(a,b), CHECK(a<b));
CREATE TABLE IF NOT EXISTS alliances(id TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 0 CHECK(active IN(0,1)), created_event_seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS alliance_members(alliance_id TEXT NOT NULL REFERENCES alliances(id), empire_id TEXT NOT NULL REFERENCES empires(id), PRIMARY KEY(alliance_id,empire_id));
CREATE TABLE IF NOT EXISTS attacks(id TEXT PRIMARY KEY, kind TEXT NOT NULL, attacker_empire_id TEXT NOT NULL, defender_empire_id TEXT NOT NULL, origin_id TEXT NOT NULL, target_id TEXT NOT NULL, attack_power INTEGER NOT NULL CHECK(attack_power>=0), allied_defense INTEGER NOT NULL DEFAULT 0 CHECK(allied_defense>=0), alliance_id TEXT, created_at INTEGER NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, success INTEGER);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, actor_did TEXT NOT NULL, request_id TEXT NOT NULL, accepted_at INTEGER NOT NULL, accepted INTEGER NOT NULL, command_hash TEXT NOT NULL, state_before_hash TEXT NOT NULL, state_after_hash TEXT NOT NULL, details_json TEXT NOT NULL, prev_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS requests(actor_did TEXT NOT NULL, request_id TEXT NOT NULL, command_hash TEXT NOT NULL, receipt_json TEXT NOT NULL, PRIMARY KEY(actor_did,request_id));
CREATE TABLE IF NOT EXISTS technocore_state(mailbox TEXT PRIMARY KEY, cursor TEXT NOT NULL, bootstrapped INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS technocore_records(record_id TEXT PRIMARY KEY, mailbox TEXT NOT NULL, seq INTEGER, ts INTEGER, accepted_at INTEGER NOT NULL, receipt_json TEXT NOT NULL);
""",
"""
CREATE TABLE IF NOT EXISTS staging_diagnostics(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at INTEGER NOT NULL,
  mailbox TEXT NOT NULL,
  record_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  details_json TEXT NOT NULL,
  UNIQUE(mailbox,record_id)
);
CREATE TABLE IF NOT EXISTS receipt_outbox(
  receipt_hash TEXT PRIMARY KEY,
  actor_did TEXT NOT NULL,
  request_id TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('PENDING','PUBLISHED')),
  publish_ref TEXT,
  readback_verified INTEGER NOT NULL DEFAULT 0 CHECK(readback_verified IN(0,1)),
  attempts INTEGER NOT NULL DEFAULT 0,
  UNIQUE(actor_did,request_id)
);
CREATE TABLE IF NOT EXISTS publication_evidence(
  receipt_hash TEXT PRIMARY KEY REFERENCES receipt_outbox(receipt_hash),
  publish_ref TEXT NOT NULL,
  verified_at INTEGER NOT NULL
);
""",
"""
ALTER TABLE attacks ADD COLUMN deadline_at INTEGER;
ALTER TABLE attacks ADD COLUMN attacker_cost_locked INTEGER NOT NULL DEFAULT 0 CHECK(attacker_cost_locked>=0);
CREATE TABLE IF NOT EXISTS attack_eligible_allies(
  attack_id TEXT NOT NULL REFERENCES attacks(id),
  empire_id TEXT NOT NULL REFERENCES empires(id),
  PRIMARY KEY(attack_id,empire_id)
);
CREATE TABLE IF NOT EXISTS attack_defenses(
  attack_id TEXT NOT NULL REFERENCES attacks(id),
  empire_id TEXT NOT NULL REFERENCES empires(id),
  amount INTEGER NOT NULL CHECK(amount>0),
  submitted_at INTEGER NOT NULL,
  PRIMARY KEY(attack_id,empire_id)
);
""",
"""
CREATE TABLE IF NOT EXISTS request_conflicts(
  actor_did TEXT NOT NULL,
  request_id TEXT NOT NULL,
  command_hash TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  PRIMARY KEY(actor_did,request_id,command_hash)
);
""",
"""
CREATE TABLE receipt_outbox_v2(
  receipt_hash TEXT PRIMARY KEY,
  actor_did TEXT NOT NULL,
  request_id TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('PENDING','PUBLISHED')),
  publish_ref TEXT,
  readback_verified INTEGER NOT NULL DEFAULT 0 CHECK(readback_verified IN(0,1)),
  attempts INTEGER NOT NULL DEFAULT 0
);
INSERT INTO receipt_outbox_v2 SELECT receipt_hash,actor_did,request_id,receipt_json,status,publish_ref,readback_verified,attempts FROM receipt_outbox;
DROP TABLE receipt_outbox;
ALTER TABLE receipt_outbox_v2 RENAME TO receipt_outbox;
""",
"""
CREATE TABLE IF NOT EXISTS empire_economy(
  empire_id TEXT PRIMARY KEY REFERENCES empires(id),
  prestige INTEGER NOT NULL DEFAULT 0 CHECK(prestige>=0),
  engineering INTEGER NOT NULL DEFAULT 0 CHECK(engineering>=0),
  knowledge INTEGER NOT NULL DEFAULT 0 CHECK(knowledge>=0),
  influence INTEGER NOT NULL DEFAULT 0 CHECK(influence>=0),
  last_settled_epoch INTEGER NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS economic_epochs(
  empire_id TEXT NOT NULL REFERENCES empires(id),
  epoch INTEGER NOT NULL CHECK(epoch>=0),
  attribution_json TEXT NOT NULL,
  PRIMARY KEY(empire_id,epoch)
);
CREATE TABLE IF NOT EXISTS offensive_fatigue(
  attack_id TEXT PRIMARY KEY REFERENCES attacks(id),
  empire_id TEXT NOT NULL REFERENCES empires(id),
  event_seq INTEGER NOT NULL CHECK(event_seq>0)
);
CREATE TABLE IF NOT EXISTS technocore_rejections(
  record_id TEXT PRIMARY KEY,
  mailbox TEXT NOT NULL,
  seq INTEGER,
  ts TEXT,
  code TEXT NOT NULL,
  observed_at INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS flop_accounts(
  empire_id TEXT PRIMARY KEY,
  available INTEGER NOT NULL DEFAULT 0 CHECK(available>=0),
  locked INTEGER NOT NULL DEFAULT 0 CHECK(locked>=0),
  last_faucet_epoch INTEGER NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS flop_quotes(
  quote_id TEXT PRIMARY KEY,
  actor_did TEXT NOT NULL,
  empire_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(amount>=0),
  counterparty_empire_id TEXT,
  expires_at INTEGER NOT NULL,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('OPEN','EXECUTED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS flop_movements(
  movement_id TEXT PRIMARY KEY,
  quote_id TEXT NOT NULL REFERENCES flop_quotes(quote_id),
  kind TEXT NOT NULL,
  from_empire_id TEXT,
  to_empire_id TEXT,
  amount INTEGER NOT NULL CHECK(amount>=0),
  epoch INTEGER NOT NULL CHECK(epoch>=0),
  settlement_ref TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('SETTLED','FAILED')),
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS flop_locks(
  lock_id TEXT PRIMARY KEY,
  empire_id TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(amount>=0),
  purpose TEXT NOT NULL,
  status TEXT NOT NULL,
  counterparty_empire_id TEXT,
  expires_at INTEGER NOT NULL,
  settlement_ref TEXT NOT NULL
);
"""
]


class Store:
    def __init__(self, path: str | Path = ":memory:", *, readonly: bool = False):
        if readonly and str(path) != ":memory:":
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, isolation_level=None)
        else:
            self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.migrate()
        if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("database integrity failure")

    def migrate(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)")
        done = {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")}
        for version, sql in enumerate(MIGRATIONS, 1):
            if version not in done:
                # executescript owns its transaction boundary in sqlite3.
                self.conn.executescript("BEGIN IMMEDIATE;\n" + sql +
                    f"\nINSERT INTO schema_migrations VALUES({version});\nCOMMIT;")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        nested = self.conn.in_transaction
        if not nested:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            if not nested:
                self.conn.execute("COMMIT")
        except Exception:
            if not nested and self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def state(self) -> dict[str, Any]:
        # Keep the v0.1 projection byte-for-byte stable. Empty v0.2 migration
        # tables must not silently change a historical v0.1 state hash.
        tables = ["config", "actors", "empires", "memberships", "github_bindings", "contribution_clusters", "contribution_evidence", "balances", "territories", "territory_edges", "alliances", "alliance_members", "attacks", "attack_eligible_allies", "attack_defenses"]
        version=self.one("SELECT value FROM config WHERE key='economic_rules_version'")
        if version and version[0]=="technical-yield-v0.2":
            tables[8:8]=["empire_economy","economic_epochs"]
            tables.append("offensive_fatigue")
        flop_version=self.one("SELECT value FROM config WHERE key='flop_economy_version'")
        if flop_version and flop_version[0]=="flop-token-economy-v0.1":
            tables.extend(["flop_accounts","flop_quotes","flop_movements","flop_locks"])
        result: dict[str, Any] = {}
        for table in tables:
            rows = [dict(r) for r in self.conn.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
            result[table] = rows
        return result

    def state_hash(self) -> str:
        return sha256(self.state())

    def close(self) -> None:
        self.conn.close()
