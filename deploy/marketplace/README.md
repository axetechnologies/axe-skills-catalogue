# Marketplace gateway (one authenticated door)

Clients call `https://api.0perator.co/v1/skills*` and `/v1/tools/find` with their Operator bearer token.

    client -> Edge Caddy -> gateway :8743 (verify at AuthGate, subscription check, vet, rate limit, audit)
                              |- reads  -> hub read-only   :8742  (public catalogue, unchanged)
                              `- writes -> hub write       :8744  (loopback, own DB hub-user.db, tenant u-<hash>)

- Entitlement: `GET /operator/verify` must return `account.status == "active"` and a `subscription` of
  `{plan, status: "active"}` with the plan in `AXE_MKT_PLANS`. No subscription means 403 `subscription_required`.
- `AXE_MKT_LEGACY_BETA=1` (default) reads an active account with no `subscription` field as plan `beta`, so the
  current testers keep working until AuthGate emits subscriptions. Set it to `0` when it does.
- Publishing: name/version/size validated, `quarantined: true, verified: false, source: user` forced, 30 writes per hour per
  account, 256 KB cap, republishing a version is a 409. `?scope=mine` reads the caller's own tenant only.
- Audit: JSONL at `AXE_MKT_AUDIT`, hashed identity only.
- Never exposed: the write hub (loopback), any `X-AXE-*` header from a client, `/v1/audit`.

Files: `com.axe.skills-write.plist`, `com.axe.skills-gateway.plist` (LaunchAgents), `Caddyfile.snippet` (edge).
Rollout order: write hub, gateway, smoke with a real token, then the Caddy block. Rollback: remove the Caddy block, `launchctl bootout` both jobs.

## Status on JL2 (2026-11-05)
Live: both LaunchAgents loaded (loopback :8743 gateway, :8744 write hub, DB `~/.axe/hub/hub-user.db`), and the Caddy block is in
`~/.axe/operator-gateway/Caddyfile` (backup `Caddyfile.bak-20261105-pre-marketplace`). Caddy's admin API is off, so a Caddyfile change
takes `launchctl kickstart -k gui/$UID/co.0perator.edge`. Public check: `api.0perator.co/v1/skills/<name>` with no token is 401.
Gateway ran with `AXE_MKT_LEGACY_BETA=1` until AuthGate (memjar/authgate `feature/operator-subscription`) is deployed and
`authgate operator subscribe --backfill-active` has run; then set it to 0 in the gateway plist and `launchctl kickstart -k gui/$UID/com.axe.skills-gateway`.
The drive on 11/05 used a stub identity service with the real hubs (no sign-in token on this box): subscriber find/publish/mine, no-subscription 403,
tenant isolation, publish forced quarantined. Not yet driven with a real AuthGate token.
Rollback: restore the Caddyfile backup and kickstart the edge, then `launchctl bootout gui/$UID/com.axe.skills-gateway` and `.../com.axe.skills-write`.

## Subscriptions live (2026-11-05, later)
AuthGate `edc7f7e` is deployed on Acropolis (image `axe-authgate:acropolis-edc7f7e`, previous source `src.prev-6ce409b`, compose backup
`compose.yml.bak-20261105-pre-subscription`, Postgres dump `/opt/axe/backups/pg/operator_auth/operator_auth-20261104-155223.dump`).
`operator subscribe --backfill-active` ran once: the 7 active accounts are plan `beta`. `AXE_MKT_LEGACY_BETA=0` is set in the gateway plist
(previous plist `~/.axe/com.axe.skills-gateway.plist.bak-20261105`). New sign-ups have no subscription until one is granted:
`ssh acropolis@192.168.1.43 docker exec axe-authgate python authgate_cli.py operator subscribe ID --plan pro`.
Real-token drive through `https://api.0perator.co` (minted throwaway tokens, since revoked): subscriber verify/find/use/publish/mine all OK,
publish forced quarantined; an active account with no subscription got 403 `subscription_required` on find and publish; no token 401.
Canary skills left behind (no delete route): `canary-gateway-drive@0.0.1` (stub tenant), `canary-real-drive@0.0.1` (tenant of mcp-e2e@axe.test);
test accounts `drive-nosub@axe.test` (rejected) and `mcp-e2e@axe.test`.

## Audit log rotation
The gateway appends one JSON line per call to `~/.axe/logs/skills-gateway-audit.jsonl` (hashed identity only) and never rotates it.
`newsyslog.skills-gateway.conf` rotates it at 5 MB, keeps 14 compressed generations, and the gateway reopens the file on each write, so no restart is needed.
Install (needs sudo, so James runs it): `sudo cp deploy/marketplace/newsyslog.skills-gateway.conf /etc/newsyslog.d/skills-gateway.conf`, then check with `sudo newsyslog -nv -f /etc/newsyslog.d/skills-gateway.conf` (dry run).
Rollback: `sudo rm /etc/newsyslog.d/skills-gateway.conf`. Rotated files stay under `~/.axe/logs/` as `skills-gateway-audit.jsonl.N.gz`.
