# Native materialized-view validation

Validated November 16, 2026 (America/Los_Angeles) for
[adapter issue #39](https://github.com/redis/redis-dbt-adapter/issues/39),
starting from adapter commit `2f686af` with the accompanying implementation.

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
