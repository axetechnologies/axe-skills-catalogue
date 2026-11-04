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
