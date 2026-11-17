# Native Redis v2 validation

The [Flight SQL qualification](../docs/validation/issues70-71-2026-11-16.md)
records macOS and Linux passes with latest driver main, deterministic publication
refusals and same-session cancellation/resource probes, plus a separate stable/main
Linux comparison. The integration pin now selects the merged Flight-enabled
engine `1988196900588c1be955b7b0cc87cd956fa47539`, which adds only the public
auth-verification Markdown correction to the qualified Flight implementation;
Redis and Flight remain
experimental. Original failing evidence is preserved in the earlier records.

## Direct-Redis qualification: November 16, 2026

The direct-Redis qualification used engine
`754f0a47164f86226dc568096ac56906ff9d2e69`, reconciled with upstream
`de5f46bf8e58a7e6e635b6d15ebcd09482b56e2f` and submitted in
[dbt-labs/dbt#17195](https://github.com/dbt-labs/dbt/pull/17195).
The [complete qualification](../docs/validation/issue40-2026-11-16.md) records
actual macOS arm64 native runs with dbt-oss 2.0.11, driver v0.0.27, Redis
Enterprise 8.6.2, verified TLS/authentication, three shards and active QPF 4x.

The Rust ADBC 1.1/concurrency audit, two smoke builds, parity fixture, full sampled
taxi workflow, docs/catalog and cleanup passed. Taxi: 82 successes and one
configured warning; empty build: 82 successes. The optional Python 3.13.16
runtime used PyArrow 26.0.0 and ADBC manager 1.12.0 without the Python dbt adapter.
The qualification lists concrete failures, candidate fixes, tests and limits.
Upstream CodeScene, CLA and fork-CI gates are tracked separately; no stock dbt
v2 or v2 Flight SQL support is claimed.

## Historical feature-parity milestone: October 2026

The feature-parity changes are merged in [engine PR #3](https://github.com/alberttwong/dbt/pull/3)
for the historical milestone below. The connection-option patch received human
verification before commit. No stock dbt v2 binary includes Redis.

Local environment: macOS arm64, dbt-oss 2.0.8, Redis 8.6.2, Redis ADBC v0.0.16,
PyArrow 25.0.1, and ADBC driver manager 1.12.0. The taxi input is the existing
January 2019 TLC CSV, sampled every 50 rows: 153,356 source rows. The project
includes the mixed-case header fixes from companion PR #73.

On October 22, 2026, the pinned engine and driver were revalidated locally on
macOS arm64 with Python 3.13.16, PyArrow 26.0.0, and ADBC driver manager 1.12.0.
All four engine Python runtime tests, the expanded feature-parity runner, and
the full native taxi runner passed, including Python models, CSV loading,
incremental/snapshot/microbatch demos, empty builds, and schema cleanup. This
runtime used an isolated environment without the v1 Python adapter. The shared
Python runtime now requires Python 3.13+; support for Python 3.11 and 3.12 has
been dropped to standardize on the validated Python 3.13 runtime.
The Linux and TLS results below refer to the earlier PyArrow 25 run.

[Linux CI passed on October 21, 2026](https://github.com/alberttwong/redis-dbt-adapter-with-project/actions/runs/39623533131) using the exact pinned engine
commit `90178580bd6f3353d758fff770fdc2c58c985ad0` and Redis ADBC v0.0.16.
It passed the smoke, expanded parity fixture, verified TLS with explicit
credentials overriding incorrect URI credentials, and the full taxi workflow.
The taxi build had 82 successes and one configured warning; its empty build
had 82 successes. Both runners completed schema cleanup. Engine PR #3 and
integration PR #74 are merged. All seven checks on PR #74 also passed.

| Scenario | Result |
| --- | --- |
| Original smoke, two builds and cleanup | Pass |
| SQL table/view/ephemeral and delete+insert | Pass |
| Python Arrow table model and output checks | Pass |
| Contract DDL, NOT NULL rejection | Pass |
| Snapshot change history and hard deletes | Pass |
| Merge update and retained unmatched rows | Pass |
| Microbatch two-day backfill and one-day replacement | Pass |
| Gzipped CSV, sampling, limit, stable row IDs | Pass |
| Persisted table/column comments in JSON catalog | Pass |
| Compact empty build | Pass |
| Full taxi build, packages, both unit tests, Python model | 82 successful results, one configured source warning |
| Taxi docs and JSON catalog | Pass with explicit build --write-catalog |
| Taxi incremental/snapshot/microbatch demos | Pass |
| Full taxi empty build | Pass, 82 successful results |
| Named connection options and reserved-option validation | Pass |
| Explicit credentials override URI credentials | Pass |
| Incorrect credentials rejected | Pass |
| TLS with untrusted certificate | Rejected, as expected |
| TLS transport with explicit test-only verification bypass | Pass |
| Trusted TLS on Linux | Pass, certificate verification enabled |

The optional Python runtime needs only PyArrow and the ADBC driver manager;
it does not install or import the v1 Python adapter. Additional pandas/polars
model packages must already be installed by the user. SQL privileges and
materialized views remain unsupported by Redis, as in v1. Static analysis and
cross-adapter replay of local Python/CSV operations remain unavailable.

The native adapter schema/SQL/profile suite previously passed 763 tests. This
feature work adds runtime, macro, artifact, and empty-fixture regressions.
The unrelated 32 adapter-library failures reproduced on the previous base
are recorded in engine PR #2; they are not treated as parity evidence.
