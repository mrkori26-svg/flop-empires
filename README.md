# FLOP Empires

> **FLOP Tools / REFERENCE APPLICATION** · demonstrates the end-to-end journey `discover -> route -> execute -> receipt -> verify -> observe` as integrations are enabled. It is not counted as external adoption.
>
> Core surfaces: [ROUTE](https://github.com/retardio73-boop/flop-session-router) · [PROVE](https://github.com/retardio73-boop/flop-conformance-lab) · [OBSERVE](https://github.com/retardio73-boop/flop-control-center)

Private, locally runnable Season 0 operational freeze implementing FLOP Empires Protocol
v0.1 plus replay-compatible Technical Yield v0.1 and manifest-selected v0.2. It
is a Python 3.12 text/CLI referee with SQLite,
signed receipts, hostile-input verification, and a deterministic simulator.

```console
python -m pip install -e ".[test]"
pytest
flop-empires init game.db --referee-did did:key:YOUR_EXTERNALLY_MANAGED_PUBLIC_KEY
flop-empires simulate --actions 100000 --seed 0 --output simulation-report.json
flop-empires state game.db
flop-empires status game.db
flop-empires staging observe staging.db --mailbox staging-example-inbox
```

`init` records only the public referee DID. It never creates or stores a signing
key; adjudicating applications inject a matching signer implementation.

Live boundaries are deliberately narrow: `GitHubVerifier.verify_evidence`
converts an explicit supported GitHub URL into typed, semantically verified
evidence, and `TechnocoreIngestor.poll` consumes finite batches from an injected
read-only `SignedMailbox`. Network credentials and production signing remain in
the injected clients; neither is persisted by FLOP Empires.

`TechnocoreHttpMailbox` is the fixed-origin live reader. It accepts only canonical
JSON commands carried in room messages, verifies the exact Ed25519
`room|nonce|text` signature again inside the ingestor, tracks generation and
sequence, rejects retention gaps, and never follows or executes message content.

No router, conformance-lab, token, payment, wallet, staking, or NFT integration is included. The browser surface is read-only and consumes canonical local state.

Current exercised capability includes `SEASON_MINUS_ONE_READY`: official GitHub API,
fixed-origin Technocore reads, dedicated DPAPI-protected staging identities,
signed action POST, signed receipt POST, verified readback, duplicate/conflict
semantics, both controlled crash windows, and a four-actor private Season -1
have been exercised. Season -1B additionally ran the integrated v0.2 engine for
165 real action records and 46 epochs with exact replay.

Season 0 is now operating under signed `Recovery v1` after the original activation
reached season start with zero players and an unmaterialized actions namespace while
Technocore was at its global room cap. The failed runtime is preserved separately;
the original activation is unchanged. Recovery v1 binds the frozen manifest to an
existing Season 0 room used as explicit duplex transport. Registration is live, the
recovered runtime has accepted a signed player registration and empire join, and both
receipts have verified public readback. See `reports/season-0-recovery-evidence-v1.md`
and `reports/season-0-recovery-evidence-v1.json` for the evidence chain.

## Public Season 0 surface

A read-only browser surface is available through:

```console
flop-empires-ui
```

By default it binds to `127.0.0.1:8765` and reads the canonical Season 0 SQLite runtime plus the frozen world/activation artifacts. Set `FLOP_EMPIRES_UI_HOST`, `FLOP_EMPIRES_UI_PORT`, or `FLOP_EMPIRES_DB` to override those defaults.

The public projection is deliberately fog-safe. It exposes territory identity, owner, capital status, adjacency, strategic value, public conflicts, active alliances, registration counts, bounded event metadata, and replay/provenance hashes. It does not expose exact stockpiles, POWER inputs, exact fortification, sensitive production, committed attack force, allied defense amounts, event payload details, or actor DIDs from the event feed.

Treaty, trade, Standing and victory semantics are reported separately as rule capabilities. They are never presented as live runtime state until corresponding canonical runtime materialization exists. The browser UI is a projection only and does not mutate the referee database.
