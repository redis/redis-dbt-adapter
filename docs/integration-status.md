# dbt integration status and remaining work

Tracking: [issue #40](https://github.com/redis/redis-dbt-adapter/issues/40).
Documentation and source reviewed November 16, 2026. This review did not run a
new Redis integration test. Historical results retain their original versions.

## Connection paths

| Path | Status | Installation and scope |
| --- | --- | --- |
| dbt Core 1.x → Redis ADBC | ✅ 🔌 Available through community-origin `dbt-redis-adbc` | [Python adapter](../v1/adapter/README.md), `dbt-core>=1.10,<2`; the example requires `>=1.10.8,<2`. Install the native Redis driver separately. |
| dbt v2 → Redis ADBC | Experimental, validated in a custom engine | Build the [Redis-enabled Rust fork](../v2/README.md#engine-implementation) at the pinned commit. Installing the Python adapter or just the driver does not register Redis in stock dbt v2. |
| dbt → ADBC Flight SQL → Redis Flight SQL server | Unverified candidate | Requires adapter connection work, the Flight SQL client driver, and a separately deployed server. Neither native adapter establishes this path. |

Both implemented paths load the Redis native library locally. Flight SQL would
instead load the Flight SQL client library in dbt and run the Redis native
driver in the server. Redis itself does not expose that Flight SQL endpoint.
The Flight datasets API is separate and cannot substitute for SQL support.

The adapter began as a community project and later
[moved to the Redis organization](../MIGRATION.md). Repository location alone
does not establish Redis, Inc. maintenance, product support, or an SLA.

## Comparison-table correction

The driver's [data-tool comparison](https://github.com/redis/redis-adbc-driver/blob/main/docs/data-engineering-adbc-support.md)
already lists dbt as ✅ 🔌, links the v1 adapter and experimental v2 fork,
distinguishes end-to-end validation from SQL replay, and leaves Flight SQL
unverified. The issue's original “row 7” is now inventory entry 10. The original
“Redis adapter still required” statement is obsolete for Core 1.x.

When reusing this comparison, link `dbt-redis-adbc` as the community-origin
connector and describe the current Redis-hosted repository separately from
maintenance or support. Suggested summary:

> Redis ADBC integration is available through `dbt-redis-adbc` for dbt Core
> 1.10–1.x. The companion project documents end-to-end workflows and functional
> tests. Experimental dbt v2 support requires a custom Rust engine; Flight SQL
> remains unverified.

## Validation evidence and limits

| Evidence | Exact version scope | What it establishes |
| --- | --- | --- |
| [v1 project and functional-suite configuration](../.github/workflows/ci.yml), [testing guide](../v1/README.md#validation-and-testing) | Redis 8.6.2; current driver pin v0.0.18; Python 3.13. Locked: Core 1.12.6, dbt-adapters 1.24.5, dbt-tests-adapter 1.20.0, ADBC manager 1.12.0, PyArrow 26.0.0. Oldest project lane: Core 1.10.8, dbt-adapters 1.16.0, manager 1.6.0, PyArrow 26.0.0. | Configured project builds, seeds, incremental/snapshot/microbatch demos, tests, docs, and empty builds. The adapter functional suite runs on locked versions only. Workflow definitions and dependency pins describe coverage; they do not prove a particular run passed. |
| [Historical native v2 Linux CI](https://github.com/alberttwong/redis-dbt-adapter-with-project/actions/runs/39623533131), October 21, 2026; [validation record](../v2/VALIDATION.md) | dbt-oss 2.0.8, engine `90178580bd6f3353d758fff770fdc2c58c985ad0`, Redis 8.6.2, Redis ADBC v0.0.16; earlier PyArrow 25 runtime | Recorded smoke and parity builds, taxi workflow, trusted TLS and credential precedence, and cleanup. Taxi build: 82 successes and one configured warning; empty build: 82 successes. |
| [Recorded native v2 macOS arm64 revalidation](../v2/VALIDATION.md), October 22, 2026 | Same engine, dbt, Redis, and driver as above; Python 3.13.16, PyArrow 26.0.0, ADBC manager 1.12.0 | Recorded Python runtime tests, parity and taxi runners, demos, empty builds, and cleanup without the v1 adapter installed. |

The [current v2 workflow](../.github/workflows/v2-native.yml) now selects driver
v0.0.18 through [upstream.json](../v2/upstream.json). That configuration change
does not retroactively validate v0.0.18 in the historical v0.0.16 runs.

The driver's [differential SQL harness](https://github.com/redis/redis-adbc-driver/tree/main/go/pgdiff)
replays captured dbt-postgres statements. It cannot establish adapter
registration, authentication, discovery, materializations, tests, or docs
generation in an actual dbt run. Conversely, the finite dbt scenarios above do
not establish every feature, platform, version, or deployment.

Native limitations include autocommit without rollback, no SQL grants or
materialized views, and table-only Python models. v2 static analysis remains
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

Assessment: a plausible transport path exists through the
[ADBC Flight SQL driver](https://arrow.apache.org/adbc/current/driver/flight_sql.html)
and [Redis Flight SQL server](https://github.com/redis/redis-apache-arrow-flight).
This is an inference from their documented interfaces, not a dbt integration
result. No Flight SQL dbt run or compatible version tuple is recorded here.

The v1 [connection layer](../v1/adapter/dbt/adapters/redis_adbc/connections.py)
maps profile fields to `adbc.redis.*` options and opens the selected library
with autocommit. Its [metadata and ingestion code](../v1/adapter/dbt/adapters/redis_adbc/impl.py)
also depends on Redis catalog/schema conventions, `adbc_get_objects`, and
`adbc_ingest`. Changing only the library path and URI is insufficient evidence
that these options and operations work through Flight SQL. The native v2
profile and driver-loading path require a separate assessment.

Remaining acceptance criteria under issue #40:

- [ ] Select a v1 or v2 adapter implementation and pin dbt/engine, Flight SQL
  client driver, Flight server, server-side Redis driver, Redis, and OS versions.
- [ ] Implement and test Flight endpoint, TLS, credentials/token, and session
  option mapping. Keep Redis-specific options on the server side where
  appropriate; document driver installation on each side and server deployment.
- [ ] Validate authenticated login, rejected credentials, verified TLS,
  catalog/schema/table/column discovery, quoting, and generated Redis SQL.
- [ ] Verify Arrow/SQL type mappings, NULLs, empty results, parameter binding,
  and seed ingestion against the pinned client/server pair. Check ingestion
  explicitly rather than assuming parity with the Redis driver's API.
- [ ] Run writes and table/view/incremental materializations, snapshots,
  dbt tests, and docs/catalog generation end to end, including connection
  concurrency, session behavior, autocommit, and cleanup after failure.
- [ ] Publish commands, artifacts, concrete failures, and unsupported features
  before marking Flight SQL supported. Generic Flight client or datasets tests
  are insufficient.

Existing SQL compatibility issues remain in the driver tracker; this checklist
does not duplicate them or claim that a transport change resolves them.
