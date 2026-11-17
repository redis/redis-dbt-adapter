# Redis v2 implementation checklist

Current baseline: [`de5f46bf8`](https://github.com/dbt-labs/dbt/tree/de5f46bf8e58a7e6e635b6d15ebcd09482b56e2f).
Upstream changes should be contributed from the [`alberttwong/dbt`](https://github.com/alberttwong/dbt)
fork. Keep the existing Python package and its `<2` dependencies in `v1/`.

## Register the adapter in the engine

- [x] Add the `redis_adbc` adapter identity to `dbt-adapter-core` and the
  typed profile variant to `dbt-schemas/src/schemas/profiles.rs`.
- [x] Map the profile fields to ADBC options in `dbt-auth`, loading the Redis
  library through the existing `dbt-adbc` driver-loading facilities. Register
  its backend as required; do not introduce a Python adapter dependency.
- [x] Cover all exhaustive adapter matches, experimental profile gating,
  profile setup, protocol adapter identities, and SQL dialect handling affected
  by the new identity. Compile and test the affected crates in the fork.

Implemented connection mapping, derived from the v1 adapter:

| Profile field | Driver configuration |
| --- | --- |
| `driver` | Absolute local shared-library path; driver loading, not a database option |
| `uri` | `uri` (Redis or TLS Redis URI) |
| `username`, `password` | Separate ADBC credential options |
| `schema` | `adbc.redis.default_schema` |
| `database` | Single catalog `redis`; validate rather than silently ignoring another catalog |
| `time_zone` | `adbc.redis.time_zone` |

V1 options `aggregate_pushdown`, `rename_rekey`, timeouts, and scalar
`driver_options` are validated. Reserved overrides are rejected; explicit
credentials override URI credentials. Auth, invalid configuration, and local TLS
checks pass. Trusted TLS and credential precedence also pass in Linux CI.

## Port relation, metadata, and SQL behavior

- [x] Render relations as `schema.table`, omitting the `redis` catalog. Preserve
  explicit quoting and identifier case. Temporary relations are unqualified.
- [x] Implement schema, relation, column, and catalog introspection through the
  driver. The v1 implementation uses ADBC `GetObjects` and Arrow metadata;
  avoid assuming another warehouse's information-schema layout.
- [x] Port the necessary Jinja macros from `v1/adapter/dbt/include/redis_adbc/`
  into the engine's macro assets, using its required review and macro tests.
  Keep the `redis_adbc__` dispatch name so package overrides can be reused.
- [x] Preserve autocommit behavior: Redis does not support SQL transactions or
  rollback. Do not send `BEGIN`/`COMMIT` as if the driver were PostgreSQL.
- [x] Define Arrow/SQL type mapping, seed ingestion or binding behavior, and
  adapter response counts. The v1 driver uses `?` placeholders.

## Prove execution before claiming support

- [x] Pass `v2/smoke.py --dbt <redis-enabled-engine> --build`, including the
  second incremental build and cleanup.
- [x] Add a manual CI workflow that builds an engine at a pinned Redis
  implementation commit and runs the fixture with the pinned driver.
- [x] Verify native Linux CI, including trusted TLS and the full taxi project.
- [x] Validate the full NYC taxi SQL project, packages and strict v2 parsing,
  source loading, contracts, persisted docs, snapshots, `merge`, `microbatch`,
  and empty builds, including the Python model and custom `adapter.load_csv_file`
  loader through the optional local Arrow runtime.
- [x] Check v2 artifact and CLI behavior before reusing the v1 CI result checks.
  Port applicable functional scenarios; the Python `dbt-tests-adapter` suite
  cannot validate a compiled v2 adapter by itself.
- [x] Document unsupported features and the migration commands; retain v1
  support while v2 is developed. The feature-parity engine and integration
  changes are merged; the adapter remains experimental in the custom engine.

## Validated milestone

Native macOS arm64 and Linux CI validation passed with dbt-oss 2.0.8, Redis 8.6.2, and Redis
ADBC v0.0.16. The original smoke, expanded parity fixture, and complete sampled
NYC taxi project pass, including Python, CSV loading, contracts, persisted docs,
merge, snapshots, microbatch, and empty builds with unit-test fixtures.
See [VALIDATION.md](VALIDATION.md) for evidence and limitations. The pinned engine
is merged in [engine PR #3](https://github.com/alberttwong/dbt/pull/3).
Linux parity and trusted TLS passed in the [manual workflow](https://github.com/alberttwong/redis-dbt-adapter-with-project/actions/runs/39623533131).

## Current contribution and API audit

[Upstream PR #17195](https://github.com/dbt-labs/dbt/pull/17195) contains the
reconciled candidate pinned by `upstream.json`. The
[November 16 record](../docs/validation/issue40-2026-11-16.md) documents a live
Rust ADBC 1.1 API/concurrency audit, current-driver smoke/parity, and full sampled
taxi validation. Driver v0.0.27 exposed refused-publication and Decimal256 gaps;
the candidate fixes those with regression coverage and bounded safe retries.

This is a submitted contribution, not upstream inclusion. Code health is tracked
in [#63](https://github.com/redis/redis-dbt-adapter/issues/63), CLA/fork-CI approval
in [#64](https://github.com/redis/redis-dbt-adapter/issues/64), and the unsupported
native v2 Flight SQL transport in [#51](https://github.com/redis/redis-dbt-adapter/issues/51).
