# dbt integration status and remaining work

Tracking: [issue #40](https://github.com/redis/redis-dbt-adapter/issues/40).
Documentation and source reviewed November 16, 2026. This review did not run a
new Redis integration test. Historical results retain their original versions.

## Connection paths

| Path | Status | Installation and scope |
| --- | --- | --- |
| dbt Core 1.x → Redis ADBC | ✅ 🔌 Available through community-origin `dbt-redis-adbc` | [Python adapter](../v1/adapter/README.md), `dbt-core>=1.10,<2`; the example requires `>=1.10.8,<2`. Install the native Redis driver separately. |
| dbt v2 → Redis ADBC | Experimental, validated in a custom engine | Build the [Redis-enabled Rust fork](../v2/README.md#engine-implementation) at the pinned commit. Installing the Python adapter or just the driver does not register Redis in stock dbt v2. |
| dbt Core 1.x → ADBC Flight SQL → Redis Flight SQL server | Implemented, with scoped local validation | Use the [v1 Flight SQL transport](../v1/adapter/README.md#flight-sql) and a separately deployed server. Flight TLS/authentication and v2 remain unverified; see the [validation record](../v1/FLIGHT_SQL_VALIDATION.md). |

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
distinguishes end-to-end validation from SQL replay, and leaves Flight SQL
unverified in that comparison. The newer v1 Flight SQL validation below has a
narrower tested scope than full deployment qualification. The issue's original “row 7” is now inventory entry 10. The original
“Redis adapter still required” statement is obsolete for Core 1.x.

When reusing this comparison, link `dbt-redis-adbc` as the community-origin
connector and describe the current Redis-hosted repository separately from
maintenance or support. Suggested summary:

> Redis ADBC integration is available through `dbt-redis-adbc` for dbt Core
> 1.10–1.x. The companion project documents end-to-end workflows and functional
> tests. Experimental dbt v2 support requires a custom Rust engine. The v1 Flight
> SQL transport has scoped local validation; Flight TLS/authentication and v2
> Flight SQL remain unverified.

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

The [v1 Flight SQL validation record](../v1/FLIGHT_SQL_VALIDATION.md), dated
November 2, 2026, reports `dbt debug` passing and 192 functional tests passing
with 26 skipped, on macOS arm64, Python 3.14.10, Core 1.12.6, ADBC manager and
Flight client 1.13.0, and PyArrow 26.0.0. It covers models, seeds, snapshots,
incremental strategies, Python models, tests, and docs/catalog generation.
The server reported `dev`, with no certified immutable build identity; Flight
TLS and authentication were disabled. Redis backend build/trust/credentials
were not independently requalified. The temporary logs are not published
artifacts. These limits prevent treating this as a fully versioned, authenticated
Flight deployment qualification.

The driver's [differential SQL harness](https://github.com/redis/redis-adbc-driver/tree/main/go/pgdiff)
replays captured dbt-postgres statements. It cannot establish adapter
registration, authentication, discovery, materializations, tests, or docs
generation in an actual dbt run. Conversely, the finite dbt scenarios above do
not establish every feature, platform, version, or deployment.

Native limitations include autocommit without rollback and table-only Python
models. Native SQL materialized views support creation, refresh, replacement,
metadata/catalog discovery, and supported nonunique indexes; see the
[materialized-view guide](../v1/README.md#materialized-views) and
[versioned validation record](../v1/MATERIALIZED_VIEW_VALIDATION.md).
The new lifecycle evidence uses the direct native ADBC transport; it does not
extend the historical Flight SQL qualification above. Native SELECT grants require dedicated Redis
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

Remaining acceptance criteria for an upstream contribution are tracked here
under issue #40:

- [ ] Rebase the Redis engine changes onto an identified `dbt-labs/dbt` commit
  and open/link an upstream adapter contribution following the
  [dbt v2 adapter guide](https://docs.getdbt.com/guides/adapter-creation-v2).
- [ ] Recheck adapter registration, profile/auth fields, driver installation
  and loading, metadata discovery, macros, and basic materializations against
  that upstream source; record the source commit and review outcome.
- [ ] Audit the target engine's required ADBC API/version surface against the
  chosen Redis driver: initialization/options, metadata, statement execution,
  binding/ingestion, Arrow types, autocommit, and error/status handling. Record
  unsupported calls and concrete failures rather than inferring completeness
  from smoke success.
- [ ] Exercise connection reuse and concurrency with multiple dbt threads,
  independent schemas, failed statements, and cleanup. Record exact engine,
  driver, Redis, OS, and optional Python runtime versions plus artifacts.
- [ ] Run smoke, parity, TLS/auth, and taxi validation on that candidate using
  the [existing commands](../v2/README.md). Record failures and unsupported
  scenarios, and link the actual CI run before expanding the support claim.

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

Remaining acceptance criteria under issue #40 (v1 implementation tracked in
[issue #36](https://github.com/redis/redis-dbt-adapter/issues/36)):

- [x] Implement a distinct v1 Flight connection/profile path, session handling,
  Redis metadata supplementation, and seed/Arrow ingestion behavior.
- [x] Record a scoped v1 functional run covering materializations, snapshots,
  type mappings, isolation, tests, and docs generation, including skips and
  concrete diagnostic failures.
- [ ] Pin Flight server and server-side Redis driver builds and independently
  qualify the Redis version and backend TLS/authentication. Record all client,
  dbt, server, Redis, and OS versions plus durable run artifacts.
- [ ] Validate Flight login, rejected credentials, verified TLS, session routing,
  concurrent connections, and cleanup after failure against that pinned pair.
  Document client/server installation and unsupported deployment features.
- [ ] Reproduce the functional coverage in that authenticated deployment;
  retain skips and failures explicitly. The earlier unauthenticated local run
  does not qualify other platforms or the full taxi dataset.
- [ ] Assess and implement the separate v2 Flight SQL profile/connection path,
  then validate metadata, generated SQL, types, writes/materializations, tests,
  and docs end to end before claiming v2 Flight SQL support.

Existing SQL compatibility issues remain in the driver tracker; this checklist
does not duplicate them or claim that a transport change resolves them.
