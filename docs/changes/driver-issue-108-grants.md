# Native SELECT grants through dedicated Redis Software ACLs

Date: 2026-11-04. Source: `0757da9`. Requestor: Albert Wong. Author: Codex.
Companion to [redis/redis-adbc-driver#108](https://github.com/redis/redis-adbc-driver/issues/108).

The requestor selected enforced SELECT mapping through dedicated ACLs, preserving
administrator ACLs and role membership. The native adapter previously skipped
all grants. Explicit `adbc.redis.rbac` now enables dbt's normal grant diff flow,
information_schema discovery, quoted grantees and one DCL statement per role.
Without configuration the warning remains. Unsupported privileges and mixed-role
bindings are rejected by the initial driver contract; Flight is unchanged.

Validation: unit suite 14 passed. Retained opt-in integration test passed with
dbt Core 1.12.6, Python 3.13 and a source-built Redis ADBC driver against an
isolated Redis Software 8.2.0-78.18 / Redis 8.6.2, Search-enabled one-shard TLS
fixture. It built an incremental model with SELECT grants, read `(42,)` using
separate reader credentials, recognized unchanged grants on a rerun, then
revoked via `grants={'select': []}` and verified NOPERM on complete reader fetch.
Provisioning fixtures ran sequentially; they own and clean up their roles/users.
No general SQL privilege or full dbt grants-suite support is claimed.

Self-reviewed code, SQL quoting, transport gating, configuration redaction and
runtime evidence. No human reviewer approval is inferred. No release included.
