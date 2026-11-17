# Native materialized-view validation

Validated November 16, 2026 (America/Los_Angeles) for
[adapter issue #39](https://github.com/redis/redis-dbt-adapter/issues/39),
starting from adapter commit `2f686af` with the accompanying implementation.

## Integration with merged named-index support

PR #49 merged into main as `31bc908`, adding table/incremental named indexes
and the shared `redis_index_sql` helper. Merged that main revision into PR #50
and resolved the overlapping adapter methods/documentation while preserving
both the general index lifecycle and materialized-view refresh reconciliation.
The existing array regressions remain enabled.

- Latest stable driver confirmed as **v0.0.27**. Combined index and
  materialized-view functional tests against that native library:
  **20 passed**, 30.86 seconds. This includes `rename_rekey` index cases,
  invalid index configurations, and materialized-view replacement/refresh.
- Full merged functional suite on native source driver
  `36f456a44fc1af7839e43ab5912a606ad8dadf92`:
  **216 passed, 13 skipped, zero failures/errors**, 125.71 seconds, using
  `pytest v1/adapter/tests/functional -n 4 -q`. Redis Software / Redis 8.8.0,
  three shards and active 4× QPF were reconfirmed for this run.
- Strict MkDocs build, Python compilation and `git diff --check`: passed.

## Driver source revalidation

Built native driver main commit
`36f456a44fc1af7839e43ab5912a606ad8dadf92` from source on November 16, 2026,
using Go **1.27.3**, macOS arm64, and the same locked Python runtime and verified
Redis Software environment described below. The adapter revision before this
validation update was `a472887`.

The source includes native catalog-write coordination
([driver PR #451](https://github.com/redis/redis-adbc-driver/pull/451)) and quoted
index column support
([driver PR #450](https://github.com/redis/redis-adbc-driver/pull/450)). These
results qualify that exact source build, independently of released v0.0.27.
ADBC GetInfo confirmed the full driver commit and Redis **8.8.0**. The built
library SHA-256 is
`7b77c2834e7d897c6ef54b967ab7d4fb71a69ea5179ce93267673f04ff693c93`.
Before the run, the management API reconfirmed three active shards, active
4× QPF, six Search workers, mnp routing, 32 connections, and noeviction.

```sh
cd v1
DRIVER_VERSION=36f456a44fc1af7839e43ab5912a606ad8dadf92 make driver-build
# Configure the dedicated authenticated TLS Software endpoint and trusted CA.
.venv/bin/python -m pytest adapter/tests/functional -n 4 -q
```

- Native build: passed.
- **Full parallel adapter suite: 194 passed, 19 skipped, zero failures/errors**,
  151.86 seconds. This includes all four materialized-view functional tests.
  The prior store-failures audit-schema teardown error did not recur.
- Strict MkDocs build and `git diff --check`: passed.
- Original native independent-table reproduction: **0 failures in 40 CTAS
  attempts** across two connections, with no adapter retries involved.
- Sequential native quoted-index reproduction: index creation and indexed reads
  passed for both `"Customer ID"` and `"CamelCase"`, on both an ordinary table
  and a materialized view.

## Audit of skipped array tests

The full-run count above predates removal of six stale array skip markers.
On the same driver source revision and Software endpoint, the formerly excluded
`TestArrayAppend`, `TestArrayConcat`, and `TestArrayConstruct` classes all passed:
**6 passed**, 4.16 seconds. These cover both dbt model builds and expected/actual
row and column-type comparisons. No array macro or driver changes were needed.
The six cases now run normally; the remaining configured skip count is **13**.
This targeted result is additional validation, not a new combined full-suite run.

The remaining exclusions are five general SQL-grant tests, three zero-copy
clone cases, two Flight SQL-only cases, one incremental Python model test,
one backslash-string-semantic test, and one unimplemented adapter
`get_catalog_for_single_relation` API test. These do not all represent missing
driver SQL capabilities: grants are scoped to native SELECT, Flight SQL requires
a separate server/transport, and the catalog exclusion is an adapter API gap.

## Environment

- macOS arm64; Python 3.13.16.
- Official checksummed Redis ADBC driver **v0.0.27**; ADBC GetInfo confirmed
  `driver_version=v0.0.27`, `vendor_version=8.8.0`.
- Native library SHA-256:
  `3af17b15fe8fbc81f49616e79a3bed815d2913d98746a880b52295c82d0d9677`.
- Dedicated disposable Redis Software instance, Redis **8.8.0**, three active
  primary shards, Search, authenticated TLS with a trusted local CA.
- Management API verified `query_performance_factor.active=true`,
  `scaling_factor=4`, six Search workers, `sched_policy=mnp`, `conns=32`.
- Locked runtime: dbt Core **1.12.6**, dbt-adapters **1.24.5**,
  dbt-tests-adapter **1.20.0**, adbc-driver-manager **1.12.0**, PyArrow **26.0.0**.

## Focused acceptance

```sh
cd v1
uv sync --locked
make driver
# Set REDIS_URI and the trusted TLS CA for the disposable Software instance.
uv run pytest adapter/tests/functional/test_materialized_view.py -q
```

**4 passed**, 13.97 seconds. These functional tests invoke real native ADBC
`dbt seed`, `dbt build`, `dbt run`, data tests, and `dbt docs generate`.
Assertions cover:

- Initial populated creation and stale rows before refresh; source changes
  become visible after a dbt rerun, with native REFRESH SQL in the debug log.
- Stored SQL stays unchanged on ordinary rerun; `--full-refresh` replaces it.
- Discovery/cache relation type `materialized_view`; `pg_matviews.ispopulated`;
  catalog type `MATERIALIZED VIEW` and persisted relation/column descriptions.
- Both directions of table/view conversion and no remaining intermediate or
  backup relations after successful runs; explicit adapter drop and discovery.
- Failed refresh and failed replacement preserve the previous target; the next
  full refresh cleans interrupted intermediates and succeeds.
- Multiple nonunique indexes, idempotent refresh, apply/continue/fail policies,
  index removal, preservation of externally named indexes, and quoted mixed-case
  index columns. Invalid options, missing columns, and UNIQUE fail explicitly.

## Oldest supported runtime smoke

A separate Python 3.13.16 environment with dbt Core **1.10.8**,
dbt-adapters **1.16.0**, adbc-driver-manager **1.6.0**, and PyArrow **26.0.0**
passed the following against the same v0.0.27 native driver and Software instance,
using one dbt thread and a dedicated schema:

1. `dbt seed`.
2. `dbt build` (create plus unique/not-null data tests).
3. `dbt build` again (refresh plus data tests).
4. `dbt build --full-refresh` (replacement plus data tests).
5. `dbt docs generate`.
6. `dbt run-operation cleanup` (drop the dedicated schema).

## Validation after rebasing onto current main

Rebased onto adapter `0f762e4` (which includes the safe publication retries
from PR #44), retaining the official native v0.0.27 library and the same verified
Software instance. `uv sync --locked` installed adapter 0.3.1 with the updated
OpenTelemetry security floor.

- Focused materialized-view suite: **4 passed**, 13.36 seconds.
- Full `pytest adapter/tests/functional -n 4 -q`: **194 passed, 19 skipped,
  1 teardown error**, 376.43 seconds. The error was unrelated to materialized
  views: `TestStoreTestFailures.test__store_and_assert` passed its test body,
  but dropping its audit schema exhausted the publication retries and returned
  the same SQLSTATE `40001` tracked in driver #448. This is not a clean full-suite
  result and does not resolve that driver issue.
- Isolated rerun of the errored store-failures test: **1 passed**, 21.38 seconds,
  including teardown. The full parallel run remains recorded as errored.
- GitHub's adapter-test job for PR #50 at `fc427bb` passed on its CI environment.
- Strict MkDocs build and `git diff --check` passed.

## Historical broader-suite failures before adapter publication retries

| Command | Result |
| --- | --- |
| `uv run pytest -n 4 -q` | 44 passed, 92 failed, 17 skipped, 65 errors; 44.59 s |
| `uv run pytest -q` (serial pytest, four dbt model threads) | 154 passed, 37 failed, 17 skipped, 2 errors; 168.77 s |

These original runs used adapter base `2f686af`, before the safe publication
retries merged in adapter PR #44. They are retained as historical failure
evidence, not the result of the rebased branch. Independent catalog changes fail with
`snapshot catalog changed concurrently; retry the statement. SQLSTATE: 40001`.
A native reproduction, with no dbt or other test workload, produced **20 failures
in 40 independent CTAS attempts** across two connections. Details and acceptance
are recorded in [driver #448](https://github.com/redis/redis-adbc-driver/issues/448).
Some later missing-relation assertions follow failed model creation.

A separate sequential native reproduction confirmed that indexing
`"Customer ID"` fails on both tables and materialized views with
`NOT_IMPLEMENTED … cannot be indexed … SQLSTATE: 0A000`; `"CamelCase"` succeeds
on both. Tracked in
[driver #449](https://github.com/redis/redis-adbc-driver/issues/449).

No PostgreSQL multi-statement transaction, uninterrupted concurrent-reader, or
dbt-postgres wire-protocol compatibility is claimed. Driver reader consistency
remains separate from this adapter acceptance.
