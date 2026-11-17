# dbt integration status and remaining work

Tracking: [issue #40](https://github.com/redis/redis-dbt-adapter/issues/40).
Live qualification completed November 16, 2026: see the
[versioned results and API audit](validation/issue40-2026-11-16.md). Historical
results below retain their original versions.

## Connection paths

| Path | Status | Installation and scope |
| --- | --- | --- |
| dbt Core 1.x → Redis ADBC | ✅ 🔌 Available through community-origin `dbt-redis-adbc` | [Python adapter](../v1/adapter/README.md), `dbt-core>=1.10,<2`; the example requires `>=1.10.8,<2`. Install the native Redis driver separately. |
| dbt v2 → Redis ADBC | Experimental, validated in a custom engine | Build the [Redis-enabled Rust fork](../v2/README.md#engine-implementation) at the pinned commit. Installing the Python adapter or just the driver does not register Redis in stock dbt v2. |
| dbt Core 1.x → ADBC Flight SQL → Redis Flight SQL server | Implemented, with scoped local validation | Use the [v1 Flight SQL transport](../v1/adapter/README.md#flight-sql) and a separately deployed server. Verified TLS/authentication and 192 functional passes on the recorded macOS source build; [qualification and limits](validation/issue40-2026-11-16.md). Native v2 Flight SQL is unsupported ([#51](https://github.com/redis/redis-dbt-adapter/issues/51)). |

The direct v1 and v2 paths load the Redis native library locally. The v1 Flight
SQL transport instead loads the Flight SQL client library in dbt and runs the
Redis native driver in the server. Redis itself does not expose that Flight SQL endpoint.
The Flight datasets API is separate and cannot substitute for SQL support.

The adapter began as a community project and later
[moved to the Redis organization](../MIGRATION.md). Repository location alone
does not establish Redis, Inc. maintenance, product support, or an SLA.

## Comparison-table correction

The driver's [data-tool comparison](https://github.com/redis/redis-adbc-driver/blob/main/docs/data-engineering-adbc-support.md)
already lists dbt as ✅ 🔌, links the v1 adapter and experimental v2 fork,
distinguishes end-to-end validation from SQL replay, and historically left
Flight SQL unverified. The November 16 source qualification below adds actual
authenticated Flight workflow evidence with finite deployment limits. The issue's original “row 7” is now inventory entry 10. The original
“Redis adapter still required” statement is obsolete for Core 1.x.

When reusing this comparison, link `dbt-redis-adbc` as the community-origin
connector and describe the current Redis-hosted repository separately from
maintenance or support. Suggested summary:

> Redis ADBC integration is available through `dbt-redis-adbc` for dbt Core
> 1.10–1.x. The companion project documents end-to-end workflows and functional
> tests. Experimental dbt v2 support requires a custom Rust engine. The v1 Flight
> SQL transport passed scoped authenticated TLS qualification. Native v2 Flight
> SQL remains unsupported.

## Validation evidence and limits

| Evidence | Exact version scope | What it establishes |
| --- | --- | --- |
| [v1 project and functional-suite configuration](../.github/workflows/ci.yml), [testing guide](../v1/README.md#validation-and-testing) | Dedicated Redis Enterprise TLS/auth environment; latest published driver selected at runtime; Python 3.13. Locked: Core 1.12.6, dbt-adapters 1.24.5, dbt-tests-adapter 1.20.0, ADBC manager 1.12.0, PyArrow 26.0.0. Oldest project lane: Core 1.10.8, dbt-adapters 1.16.0, manager 1.6.0, PyArrow 26.0.0. | Configured project builds, seeds, incremental/snapshot/microbatch demos, tests, docs, and empty builds. The adapter functional suite runs on locked versions only. Workflow definitions and dependency pins describe coverage; they do not prove a particular run passed. |
| [Historical native v2 Linux CI](https://github.com/alberttwong/redis-dbt-adapter-with-project/actions/runs/39623533131), October 21, 2026; [validation record](../v2/VALIDATION.md) | dbt-oss 2.0.8, engine `90178580bd6f3353d758fff770fdc2c58c985ad0`, Redis 8.6.2, Redis ADBC v0.0.16; earlier PyArrow 25 runtime | Recorded smoke and parity builds, taxi workflow, trusted TLS and credential precedence, and cleanup. Taxi build: 82 successes and one configured warning; empty build: 82 successes. |
| [Recorded native v2 macOS arm64 revalidation](../v2/VALIDATION.md), October 22, 2026 | Same engine, dbt, Redis, and driver as above; Python 3.13.16, PyArrow 26.0.0, ADBC manager 1.12.0 | Recorded Python runtime tests, parity and taxi runners, demos, empty builds, and cleanup without the v1 adapter installed. |

The [current v2 workflow](../.github/workflows/v2-native.yml) now selects the
latest published driver through [upstream.json](../v2/upstream.json), matching
`latest` in the [v1 driver selector](../v1/scripts/driver-version). That moving
selection does not identify or retroactively validate a driver release in the
historical v0.0.16 runs; retain the resolved release in each new run's evidence.

The [November 16 qualification](validation/issue40-2026-11-16.md) adds:

- Native dbt-oss **2.0.11** at engine commit
  `754f0a47164f86226dc568096ac56906ff9d2e69`, against Redis Enterprise **8.6.2**
  with three shards, Search, active QPF 4x, verified TLS and named-user auth;
  driver **v0.0.27**, the latest stable release at build/recheck.
- A passing live Rust ADBC 1.1 API/concurrency audit, two smoke builds, expanded
  parity, credential precedence, and full sampled taxi workflows. Taxi:
  **82 successes / one configured warning**; empty build: **82 successes**.
- Authenticated TLS v1 Flight SQL: **192 passed, 26 skipped, no warnings**, plus
  **5 security/session probes**. Public Flight source
  `4d91e37135080be7f0eeb770fc89fa7adeb14bc8` was built with the latest stable
  Redis driver. Core 1.12.6, Python 3.13.16, manager/client 1.13.0, PyArrow 26.0.0.

The [earlier November 2 Flight record](../v1/FLIGHT_SQL_VALIDATION.md) used an
unversioned `dev` server with Flight TLS/auth disabled. Those historical limits
remain attached to that run; they do not describe the new authenticated source
qualification. Both records describe finite tests, not every deployment.

The driver's [differential SQL harness](https://github.com/redis/redis-adbc-driver/tree/main/go/pgdiff)
replays captured dbt-postgres statements. It cannot establish adapter
registration, authentication, discovery, materializations, tests, or docs
generation in an actual dbt run. Conversely, the finite dbt scenarios above do
not establish every feature, platform, version, or deployment.

Native limitations include autocommit without rollback, no materialized views,
and table-only Python models. Native SELECT grants require dedicated Redis
Software ACLs; see the [grant scope](../v1/README.md#sql-grants-through-dedicated-redis-software-acls). v2 static analysis remains
disabled. See the [v1 limitations](../v1/adapter/README.md#features-and-limitations)
and [v2 validation record](../v2/VALIDATION.md) before adopting either path.

## dbt v2 upstream contribution

The [implementation checklist](../v2/IMPLEMENTATION.md) covers registration,
profile/auth mapping, metadata discovery, SQL macros, materializations, driver
loading, and actual native integration runs. Those milestones were implemented
in the [engine fork](https://github.com/alberttwong/dbt/pull/3), with historical
tracking in [issue #27](https://github.com/redis/redis-dbt-adapter/issues/27).
They do not establish inclusion in `dbt-labs/dbt`.

The assessed upstream contribution and candidate-validation milestones are now
complete within #40's tracking scope:

- [x] Reconcile with identified upstream source
  `de5f46bf8e58a7e6e635b6d15ebcd09482b56e2f` and submit
  [dbt-labs/dbt#17195](https://github.com/dbt-labs/dbt/pull/17195).
- [x] Recheck registration, profile/auth mapping, driver loading, metadata,
  macros, and materializations; compile the reconciled native engine.
- [x] Run the live Rust ADBC 1.1 surface/concurrency audit and record its exact
  versions, API coverage and limits in [the qualification](validation/issue40-2026-11-16.md).
- [x] Exercise four isolated connections, reuse after failed statements, and
  cleanup; verify credential precedence over TLS.
- [x] Record actual smoke, parity, Python/CSV, docs/catalog, and full taxi runs.

Upstream inclusion is still pending. [#63](https://github.com/redis/redis-dbt-adapter/issues/63)
tracks the CodeScene quality gate, and [#64](https://github.com/redis/redis-dbt-adapter/issues/64)
tracks the contributor CLA and maintainer-only fork-CI approval. The stock dbt
v2 executable does not acquire Redis support from a submitted PR.

## Flight SQL feasibility and acceptance criteria

The v1 path is implemented and has the finite validation described above.
It uses the [ADBC Flight SQL driver](https://arrow.apache.org/adbc/current/driver/flight_sql.html)
and [Redis Flight SQL server](https://github.com/redis/redis-apache-arrow-flight).
A separate v2 transport remains an inferred candidate, with no recorded run.

The v1 [connection layer](../v1/adapter/dbt/adapters/redis_adbc/connections.py)
now maps `transport: flightsql` separately from native Redis options and
preserves SQL sessions with cookie middleware. Its
[metadata and ingestion code](../v1/adapter/dbt/adapters/redis_adbc/impl.py)
supplements Flight metadata from Redis SQL and handles empty Arrow ingestion.
The [validation record](../v1/FLIGHT_SQL_VALIDATION.md) records why changing only
the library and URI failed: `adbc.redis.default_schema` was an unknown option.
These changes establish an implemented v1 route, rather than generic Flight
endpoint availability. Native v2 profile/loading changes require separate work.

The Flight milestones and follow-up boundaries are explicit:

- [x] Implement a distinct v1 profile/connection path, session handling,
  Redis metadata supplementation, and Arrow ingestion.
- [x] Build committed public Flight source with the **latest stable Redis ADBC
  release on every invocation**, recording resolved revisions and binary identity.
- [x] Independently verify the Redis Enterprise backend version, QPF, TLS/auth,
  and rejection cases; qualify the separate Flight TLS/authentication hop.
- [x] Run concurrent session/failure probes and the full authenticated v1
  functional suite, retaining skip counts and test summaries.
- [x] Assess the separate v2 path through actual configuration probes, record
  the unsupported-profile/URI failures, and track implementation in
  [#51](https://github.com/redis/redis-dbt-adapter/issues/51).

Native v2 Flight SQL is **not implemented or claimed**. Other platforms,
multireplica Flight deployments, and the full v1 taxi dataset over Flight are
outside the recorded local qualification. The new Linux workflow must be
judged by its actual run results, not by its presence.

Concrete regressions and fixes are tracked in
[#58](https://github.com/redis/redis-dbt-adapter/issues/58),
[#59](https://github.com/redis/redis-dbt-adapter/issues/59),
[#60](https://github.com/redis/redis-dbt-adapter/issues/60),
[#61](https://github.com/redis/redis-dbt-adapter/issues/61), and
[#62](https://github.com/redis/redis-dbt-adapter/issues/62). Existing SQL
compatibility issues remain separately tracked in the driver repository.
