<img referrerpolicy="no-referrer-when-downgrade" src="https://static.scarf.sh/a.png?x-pxid=1bdeb56d-a61a-44fa-b80a-d6890ff6e885" />

# dbt Redis adapter: NYC taxi example project

Run the commands in this guide from `v1/` (`cd v1` from the repository root).
The [repository overview](../README.md) describes the v1/v2 layout.

[![CI](https://github.com/redis/redis-dbt-adapter/actions/workflows/ci.yml/badge.svg)](https://github.com/redis/redis-dbt-adapter/actions/workflows/ci.yml)

A dbt Core project that tests the dbt Redis adapter, which is built on the
[Redis ADBC driver](https://github.com/redis/redis-adbc-driver). It does
three things:

- loads the NYC TLC yellow-taxi trips CSV into Redis,
- transforms it with ordinary dbt SQL: views, tables, an incremental MERGE
  fact table, a microbatch model, a snapshot, a model contract, joins, window
  functions, CTEs and `QUALIFY`, plus a Python model over Arrow,
- tests and documents it with dbt's standard commands, and stores the model
  descriptions in Redis as comments.

dbt's own default materializations do the work: tables, views, incremental
models (temporary tables plus `MERGE` or delete+insert) and snapshots. The SQL
dbt generates runs on the driver unchanged.

```
dbt  ──►  dbt-redis-adbc (adapter/)  ──►  adbc_driver_manager  ──►  libadbc_driver_redis  ──►  Redis 8
          Python + Jinja                  ADBC DB-API              SQL → FT.AGGREGATE / HASH
```

## Contents

- [Quick start](#quick-start)
- [Project guide](#project-guide)
- [Validation and testing](#validation-and-testing)
- [Repository reference](#repository-reference)
- [Adapter reference](#adapter-reference)
- [Compatibility and limitations](#compatibility-and-limitations)
- [Redis operations](#redis-operations)
- [Data source](#data-source)

## Quick start

### Requirements

You need Docker, [uv](https://docs.astral.sh/uv/) (it provides Python
3.13 for dbt), and network access to hub.getdbt.com for `dbt deps`.
Building the driver from source also needs Go 1.26.6 or newer and a C
toolchain; on macOS arm64 and Linux (x86-64, arm64) the prebuilt one is used.
The driver's repo, [redis/redis-adbc-driver](https://github.com/redis/redis-adbc-driver),
is public. Releases download through the [GitHub CLI](https://cli.github.com/)
when logged in, or through HTTPS without authentication.

### Set up the environment

```bash
make setup
```

`make setup` does four things:

- runs `uv sync` and `dbt deps` (dbt_utils, and the local `redis_adbc_utils`)
- puts the driver in `driver/`: the prebuilt library from the pinned
  release (`v0.0.18`, in `scripts/driver-version`), after checking its SHA-256.
  Where the release has no build (another platform, or `DRIVER_VERSION` set
  to a commit) it builds the driver from source instead; `make driver-build`
  always does
- downloads the CSV into `data/`
- starts Redis **8.6.2** on port 6380, matching CI. [Redis Cloud](https://redis.io/docs/latest/operate/rc/databases/version-management/)
  supports Redis 8.6 and may run a different patch release

### Build the project

```bash
make all
```

`make all` runs `dbt debug`, `seed`, `run-operation load_raw_trips`, `build`
and `docs generate`. Three demos show what happens across runs.

### Run the demos

Load the first half of January, then the rest: `fct_trips` merges the new trips, and `agg_zone_daily` replaces the zone-days they touch (delete+insert on a composite key):

```bash
make incremental-demo
```

Rename a zone between two snapshots; its history keeps both versions:

```bash
make snapshot-demo
```

Backfill January 1–3 as three daily batches (run in parallel), then re-run
January 2 alone, which replaces only that day:

```bash
make microbatch-demo
```

Use `make docs-serve` to browse the docs and lineage graph.

### Configure the connection

Redis is published on **6380** so it doesn't collide with a local Redis on
6379. Override the connection with `REDIS_URI` (for example
`rediss://host:port/0` for Redis Cloud), credentials with `REDIS_USERNAME` and
`REDIS_PASSWORD`, the session time zone with `REDIS_TIME_ZONE` (UTC by
default), and the driver location with `REDIS_ADBC_DRIVER`. A password
in `REDIS_URI` works too; `dbt debug` and the logs show it as `****`. Redis
Flex (RAM + SSD) databases aren't supported: their Search lacks features every
table needs, so the driver refuses them when it connects.

## Project guide

### dbt command coverage

| Command | What happens in Redis |
|-|-|
| `dbt debug` | Opens an ADBC connection. The driver checks that the Query Engine is available (`FT._LIST`) and that `FT.AGGREGATE` works, which is how it refuses Redis Flex |
| `dbt seed` | 4 lookup CSVs (zones, payment types, rate codes, vendors), loaded with ADBC bulk ingest; reloads use `TRUNCATE` |
| `dbt run-operation load_raw_trips` | Streams the 134 MB gzipped CSV with pyarrow, keeps every 50th row (~153k trips across January), adds `trip_id` (the trip's row number in the file), and bulk-ingests it into `raw.yellow_tripdata` in 6–10 s |
| `dbt run` | 5 views and 8 tables, rebuilt with dbt's create-then-`ALTER … RENAME` swap, and `agg_daily_revenue_zscores`, a Python model: dbt reads `agg_daily_revenue` into its own process as a pyarrow Table, and the result is bulk-ingested into the new table; plus 2 incremental models built from a `CREATE TEMPORARY TABLE`: `fct_trips` with `MERGE`, and `agg_zone_daily` with delete+insert on `(pickup_date, pickup_location_id)`. `dim_zones` has an enforced contract, so it's created from its DDL (with `NOT NULL` and `CHECK` constraints) and then filled with `INSERT`. The marts' descriptions are stored with `COMMENT ON` |
| `dbt run --event-time-start … --event-time-end …` | `fct_trips_microbatch` (off unless `microbatch_demo` is set): one batch per pickup day; each batch deletes its day, then inserts it |
| `dbt snapshot` | `zones_snapshot`: SCD type 2 history of the zone lookup (check strategy; a deleted zone gets a closing version), written by dbt's snapshot `MERGE` |
| `dbt test` / `dbt build` | 60 data tests (`unique`, `not_null`, `accepted_values`, `relationships`, dbt_utils' `unique_combination_of_columns` / `accepted_range`, custom generic `non_negative` / `in_range`, 5 singular tests, one of which checks the Python model's z-scores against SQL) and 2 unit tests |
| `dbt show`, `dbt compile`, `dbt ls` | Previews, inline queries, and the analysis in `analyses/` |
| `dbt build --empty --exclude-resource-type snapshot` | Builds and tests every model with no rows, in about 6 s. dbt reads each ref and source as `(select * from … where false limit 0)`, which the driver answers without reading the table. Tables, views and seeds are left empty (a view keeps the `where false limit 0` in its SQL; incremental models keep their rows), so run `make all` afterwards. Leave out the snapshot: with an empty source, `hard_deletes: new_record` would record every zone as deleted |
| `dbt docs generate` | Catalog built from ADBC `GetObjects` (column types, tables vs views), with the comments the marts store through `persist_docs` |

A clean `make all` takes 1.5–2 minutes on a laptop. It ends with 82 passes and 1
**intended** warning: the source test flags a $623,261.66 fare in the raw
data, which staging filters out.

## Validation and testing

### Continuous integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every pull
request and push to `main`, against Redis 8.6.2 and the pinned driver:

- `make all`, failing on any error and unless the build gives exactly
  `PASS=82 WARN=1`
- the three demos, checking the numbers they print
- `dbt build --empty --exclude-resource-type snapshot`

[`scripts/ci_check.py`](scripts/ci_check.py) does the checks. It runs on
Python 3.13 with the locked versions and with the oldest ones
the `pyproject.toml` files allow: dbt-core 1.10.8 (the first 1.10 release
that accepts the `arguments:` the tests are written with), dbt-adapters 1.16,
adbc-driver-manager 1.6 and pyarrow 26. Each run takes 3–5 minutes.

CI also runs [dbt's adapter test suite](#dbts-adapter-test-suite) on Python
3.13, with the locked versions only: dbt-tests-adapter needs newer
dbt packages than the oldest ones.

Nightly, all of it runs against the driver's latest release, so a driver change
that breaks the project shows up before the pin is bumped. To test another
release or a driver commit, run the workflow by hand with `driver_version`.

CI also audits the locked Python runtime and test dependencies and the optional
v2 Python runtime with `pip-audit`. The current runtime uses PyArrow 26 and the
test suite uses Polars 2. Python 3.13 is the minimum supported version. The project
constrains certifi to 2026.10.19 or newer to address GHSA-6q48-6c7w-9gw2. See
[dependency upgrade notes](DEPENDENCIES.md) for upstream constraints that prevent
some transitive dependencies from reaching their latest release.

CI downloads releases from the public `redis/redis-adbc-driver` repository
using the built-in `github.token` for GitHub API requests. Source builds clone
the public repository. No separate driver repository secret is required.

### dbt's adapter test suite

The project tests the dbt features it uses. [`adapter/tests/functional/`](adapter/tests/functional)
runs dbt Labs' [`dbt-tests-adapter`](https://github.com/dbt-labs/dbt-adapters/tree/main/dbt-tests-adapter)
suite, which other adapters run too, against the adapter. That covers the rest:
- ephemeral models
- model, seed, snapshot and run hooks
- `dbt clone` and `dbt retry`
- `--store-failures` and `--sample`
- both snapshot strategies and their `hard_deletes` modes
- `on_schema_change` and `incremental_predicates`
- contracts and constraints
- every cross-database macro
- `persist_docs`, unit tests, query comments, relation caching and concurrency

```bash
make adapter-tests
```

It runs `uv run pytest -n 4` against `REDIS_URI` (the same variables as the
project). Each test class creates its own schemas and drops them afterwards,
but use a scratch Redis anyway. It takes about a minute.

Where a test's fixture is Postgres SQL, the test module overrides the fixture,
not the adapter. For example:
- a contract on `select 1 as id` declares `bigint`, the driver's type for an
  integer literal (Postgres's is `integer`);
- dates are ISO, not `'09/01/2023'`;
- relations render as `schema.table`.

Skipped, with the reason in the test:
- grants and materialized views
- zero-copy `dbt clone` (dbt clone creates views)
- arrays
- incremental Python models (Python models are tables)
- backslash escapes (standard SQL strings, as dbt-postgres skips)
- `get_catalog_for_single_relation`, which dbt-core never calls

The pinned driver supports all snapshot tests, including `dbt_valid_to_current`
with `date(x)`; these run as ordinary tests so regressions fail CI.

## Repository reference

### Project layout

Paths below are relative to `v1/`.

```
models/
  staging/        views over raw + seeds: rename, type, filter, derive hour/weekday/duration
  intermediate/   int_trips_enriched: trips ⋈ zones (×2) ⋈ payment types ⋈ rate codes ⋈ vendors
  marts/          fct_trips (incremental MERGE), agg_zone_daily (incremental delete+insert on a
                  composite key), fct_trips_microbatch (optional), dim_zones
                  (enforced contract), agg_daily_revenue (7-day rolling average, LAG, RANK),
                  agg_top_pickup_zones (RANK … QUALIFY), agg_hourly_demand, agg_borough_flows,
                  agg_payment_mix, agg_airport_trips, agg_daily_revenue_zscores (a Python model,
                  pyarrow)
snapshots/        zones_snapshot (SCD type 2 of the zone lookup)
seeds/            taxi_zone_lookup, payment_types, rate_codes, vendors
macros/           load_raw_trips and rename_zone (run-operations), day_part
tests/            generic (non_negative, in_range) and singular tests, including dbt's
                  cross-database macros
analyses/         top_pickup_zones_by_day_part
adapter/          the dbt-redis-adbc adapter package (installed editable by uv), and
                  tests/functional: dbt's adapter test suite
redis_adbc_utils/ redis_adbc__ overrides for dbt_utils, dbt_date and dbt_expectations macros
scripts/          download_driver.sh, build_driver.sh, driver-version, download_data.sh,
                  ci_check.py (CI's checks)
```

### Project variables

Useful vars (defaults are in `dbt_project.yml`):

| Var | Default | Meaning |
|-|-|-|
| `raw_trips_sample_every` | `50` | Keep every Nth CSV row. `1` loads all ~7.7M rows, which needs several GB of Redis memory |
| `raw_trips_limit` | none | Cap on rows loaded |
| `trips_start` / `trips_end` | all of January 2019 | Pickup window kept by staging |
| `max_total_amount` | `2000` | Larger totals are treated as data errors |
| `lookback_hours` | `6` | Hours before the latest loaded pickup that each incremental run re-merges |
| `top_zones_per_borough` | `3` | Zones kept per borough by `agg_top_pickup_zones` |
| `microbatch_demo` | `false` | Enables `fct_trips_microbatch` |

## Adapter reference

### Responsibilities

dbt only connects to a database through an adapter package, and there is no
generic ADBC adapter. `adapter/` is a small one: about 780 lines of Python and
290 lines of macros. The driver runs the SQL of dbt's default macros and
materializations, so the adapter covers what isn't SQL:

| Area | Adapter |
|-|-|
| Connection | `adbc_driver_manager` DB-API, autocommit. The driver has no transactions: it accepts dbt's `BEGIN`/`COMMIT` as no-ops, and a `SET LOCAL` lasts until the model's `COMMIT`, as on Postgres. Results over 65,536 rows stream from the driver, so an error in a later batch is raised as dbt reads the rows; the adapter reports it as a database error, like one from the query. Ctrl-C and `--fail-fast` cancel the running statements and streamed results (ADBC `StatementCancel`); each fails with `CANCELLED`, which the adapter reports as a runtime error rather than a database error |
| Metadata | Relations, columns and the docs catalog come from ADBC `GetObjects`; table comments come from `information_schema.tables`. Relations are matched with their case, since the driver keeps schema and table names as written (`alias='MyTable'` works). Column types are parsed as dbt-postgres reports them (`numeric` with precision and scale, `character varying` with its length) |
| `persist_docs` | Descriptions are stored with `COMMENT ON TABLE` / `VIEW` / `COLUMN`; the marts turn it on |
| `grants` | Skipped with a warning (see [Known limitations](#known-limitations)) |
| Temporary tables | `make_temp_relation` renders them unqualified (a schema-qualified name always means a permanent table), and their columns are looked up under `pg_temp` |
| Incremental strategies | `append`, `delete+insert` (the default with a `unique_key`), `merge`, and `microbatch` (each batch replaces its `event_time` window; batches can run in parallel) |
| Seed reloads | A reload without `--full-refresh` checks the CSV's columns before truncating, so a mismatch leaves the table as it was (there's no transaction to roll the `TRUNCATE` back) |
| Loading | Seeds and the raw CSV go through Arrow bulk ingest, which is much faster than INSERTs. The driver converts each seed value to its column's type as an INSERT would, and supplies the Arrow type for each of the raw CSV's SQL column types |
| Python models | Run in the dbt process, as dbt-duckdb runs them: Redis has no Python runtime, but the driver evaluates most SQL in the dbt process too. `dbt.ref()` and `dbt.source()` return a `pyarrow.Table` (`select * from …`, read with `fetch_arrow_table()`); `session` is the thread's ADBC DB-API connection, for running SQL. `model()` returns a pyarrow Table or RecordBatchReader, a pandas or polars DataFrame (a pandas index is dropped), or anything with the Arrow stream interface; it's bulk-ingested into the `__dbt_tmp` table, and dbt's rename swap finishes the job. The adapter's `table` materialization is dbt's, with Python added; tracebacks give the model file's line numbers. As dbt specifies, `--empty` and `--sample` don't limit a Python model's refs (sources are) |
| Cross-database macros | dbt-core's defaults work natively except two: `safe_cast` uses the driver's `TRY_CAST`, and `listagg` with `limit_num` raises a clear error (it needs arrays). `tests/assert_cross_db_macros.sql` checks them all |
| Model contracts | An enforced contract creates the table from its DDL, then inserts the rows (as on dbt-postgres). `not_null` and `check` are enforced by the driver; `primary_key`, `unique` and `foreign_key` are accepted but not enforced (dbt warns) |
| Small dialect bits | `?` bind parameters, `CURRENT_TIMESTAMP` (and `current_timestamp_in_utc_backcompat` in UTC, which dbt's default isn't in a non-UTC session), `validate_sql` with a query that can't return rows (the driver has no `EXPLAIN`), a subquery wrapper for `dbt show --limit`, and no alias on the subqueries `--empty` and microbatch put around refs, so a model's own alias (`from {{ ref('x') }} z`) still works |

### Package compatibility

dbt looks for a package macro's adapter variants only in the
root project and the package itself, so the adapter can't fix a package's
`default__` macros that are wrong here. [`redis_adbc_utils/`](redis_adbc_utils/README.md)
holds those fixes:
- `dbt_utils.deduplicate`: the default drops rows with NULLs.
- dbt_expectations' regex `flags`: the default ignores them.
- dbt_date's day and month names, and its week and ISO-week macros: the
  defaults use Snowflake semantics.

This project installs it with dbt_utils and puts it first in
`dispatch:`. Copy that setup to use those packages with Redis.

### Profile configuration

Profile options (`profiles.yml`): `driver` (the library's path; without an
extension, the adapter adds `.dylib`, `.so` or `.dll`), `uri`, `username`,
`password`, `database` (optional; always `redis`), `schema`, `threads`,
`aggregate_pushdown` (`exact` / `all` / `none`), `rename_rekey` (see
[Looking at the data in Redis](#looking-at-the-data-in-redis)), and:

- `time_zone`: the session time zone, for example `America/New_York` (UTC
  by default). `current_timestamp` shows in it, `localtimestamp` and
  snapshots' `dbt_valid_from` / `dbt_valid_to` are its local time, and
  `TIMESTAMP` ↔ `TIMESTAMP WITH TIME ZONE` conversions use it, as on
  Postgres. So do seeds: a timestamp without an offset in a
  `TIMESTAMP WITH TIME ZONE` column is a local time, as on dbt-postgres.
- `read_timeout` / `write_timeout`: how long the client waits for each reply
  and to send each command: `30s`, `10m`, a number of seconds, or `0` for no
  timeout (5 minutes by default). Raise `read_timeout` on a cluster or a
  busy server.
- `driver_options`: any other
  [driver option](https://github.com/redis/redis-adbc-driver#options),
  passed as is, for example `{adbc.redis.stream_batch_rows: 10000}`. The
  driver refuses an unknown one when dbt connects. Options that have a
  profile key of their own (`adbc.redis.time_zone`, `password`, …) must be
  set with it.

`dbt debug` shows these options. A profile key the adapter doesn't know is
ignored with a warning.

## Compatibility and limitations

### Driver issues found along the way

Building this project turned up these issues, all filed on
[redis/redis-adbc-driver](https://github.com/redis/redis-adbc-driver/issues).
All of them are fixed in the pinned driver, v0.0.18.

| Issue | Fixed in |
|-|-|
| [#13](https://github.com/alberttwong/redis-adbc-driver/issues/13) Bound string parameters read freed memory | [#15](https://github.com/alberttwong/redis-adbc-driver/pull/15) |
| [#17](https://github.com/alberttwong/redis-adbc-driver/issues/17), [#18](https://github.com/alberttwong/redis-adbc-driver/issues/18) Slow `IN (SELECT …)` (57 s → 0.9 s) and correlated `EXISTS` (28 s → 2 ms) | [#38](https://github.com/alberttwong/redis-adbc-driver/pull/38) |
| [#19](https://github.com/alberttwong/redis-adbc-driver/issues/19) Window functions | [#35](https://github.com/alberttwong/redis-adbc-driver/pull/35) |
| [#20](https://github.com/alberttwong/redis-adbc-driver/issues/20) `MERGE`, `UPDATE … FROM`, `DELETE … USING` | [#29](https://github.com/alberttwong/redis-adbc-driver/pull/29) |
| [#21](https://github.com/alberttwong/redis-adbc-driver/issues/21) Temporary tables | [#30](https://github.com/alberttwong/redis-adbc-driver/pull/30) |
| [#22](https://github.com/alberttwong/redis-adbc-driver/issues/22) Renaming views | [#27](https://github.com/alberttwong/redis-adbc-driver/pull/27) |
| [#23](https://github.com/alberttwong/redis-adbc-driver/issues/23) `INSERT … (SELECT)`, `TRUNCATE`, `DROP … CASCADE` | [#25](https://github.com/alberttwong/redis-adbc-driver/pull/25) |
| [#24](https://github.com/alberttwong/redis-adbc-driver/issues/24) `ROUND`, `SUBSTRING`, `NULLIF` and other scalar functions | [#28](https://github.com/alberttwong/redis-adbc-driver/pull/28) |
| [#31](https://github.com/alberttwong/redis-adbc-driver/issues/31), [#32](https://github.com/alberttwong/redis-adbc-driver/issues/32) `SELECT DISTINCT` / `DISTINCT ON`, qualified `t.*` | [#39](https://github.com/alberttwong/redis-adbc-driver/pull/39) |
| [#33](https://github.com/alberttwong/redis-adbc-driver/issues/33) `CONCAT` returned NULL for any NULL argument | [#34](https://github.com/alberttwong/redis-adbc-driver/pull/34) |
| [#36](https://github.com/alberttwong/redis-adbc-driver/issues/36) Wrong results: rounded constants pushed into the index (`int_col > 1.5`) | [#40](https://github.com/alberttwong/redis-adbc-driver/pull/40) |
| [#37](https://github.com/alberttwong/redis-adbc-driver/issues/37) Slow literal `IN` lists over 1,000 values (66 s → 1 s) | [#41](https://github.com/alberttwong/redis-adbc-driver/pull/41) |
| [#43](https://github.com/alberttwong/redis-adbc-driver/issues/43) Column `DEFAULT`s accepted but never applied | [#57](https://github.com/alberttwong/redis-adbc-driver/pull/57) |
| [#44](https://github.com/alberttwong/redis-adbc-driver/issues/44), [#45](https://github.com/alberttwong/redis-adbc-driver/issues/45), [#50](https://github.com/alberttwong/redis-adbc-driver/issues/50) `TRY_CAST`, `%` on NUMERIC, `DATEADD` / `DATEDIFF` (dbt's `dateadd`, `datediff`, `last_day`, `date_spine`) | [#56](https://github.com/alberttwong/redis-adbc-driver/pull/56) |
| [#46](https://github.com/alberttwong/redis-adbc-driver/issues/46), [#47](https://github.com/alberttwong/redis-adbc-driver/issues/47) `STRING_AGG`, `BOOL_OR`, `ANY_VALUE`, statistics and percentiles; `FILTER`, `IGNORE NULLS`, frame `EXCLUDE` (dbt's `listagg`, `bool_or`, `any_value`) | [#62](https://github.com/alberttwong/redis-adbc-driver/pull/62) |
| [#48](https://github.com/alberttwong/redis-adbc-driver/issues/48) `GROUPING SETS`, `ROLLUP`, `CUBE` | [#59](https://github.com/alberttwong/redis-adbc-driver/pull/59) |
| [#49](https://github.com/alberttwong/redis-adbc-driver/issues/49) Regular expressions | [#61](https://github.com/alberttwong/redis-adbc-driver/pull/61) |
| [#51](https://github.com/alberttwong/redis-adbc-driver/issues/51) `RETURNING`, `UPDATE … SET (a, b) = (…)` | [#58](https://github.com/alberttwong/redis-adbc-driver/pull/58) |
| [#52](https://github.com/alberttwong/redis-adbc-driver/issues/52) `WITH RECURSIVE`, `LATERAL`, `ANY` / `ALL`, `NATURAL JOIN`, `GENERATE_SERIES` | [#68](https://github.com/alberttwong/redis-adbc-driver/pull/68) |
| [#53](https://github.com/alberttwong/redis-adbc-driver/issues/53) JSON functions | [#64](https://github.com/alberttwong/redis-adbc-driver/pull/64) |
| [#54](https://github.com/alberttwong/redis-adbc-driver/issues/54) Renamed tables keep their old key prefix (opt-in fix: `rename_rekey`) | [#69](https://github.com/alberttwong/redis-adbc-driver/pull/69) |
| [#72](https://github.com/alberttwong/redis-adbc-driver/issues/72) `COMMENT ON` (dbt's `persist_docs`) | [#73](https://github.com/alberttwong/redis-adbc-driver/pull/73) |
| [#74](https://github.com/alberttwong/redis-adbc-driver/issues/74) `WHERE false` / `LIMIT 0` ran the whole query (dbt's contract checks, `--empty`: 5 s → 2 ms on `dim_zones`) | [#77](https://github.com/alberttwong/redis-adbc-driver/pull/77) |
| [#75](https://github.com/alberttwong/redis-adbc-driver/issues/75) Column-level `CHECK` / `REFERENCES` didn't parse; `CHECK` wasn't enforced | [#76](https://github.com/alberttwong/redis-adbc-driver/pull/76) |
| [#78](https://github.com/alberttwong/redis-adbc-driver/issues/78) Unknown functions were only caught when a row was evaluated, so they passed contract checks and `--empty` | [#79](https://github.com/alberttwong/redis-adbc-driver/pull/79) |
| [#82](https://github.com/alberttwong/redis-adbc-driver/issues/82) Wrong results: a table re-created after a concurrent `DROP` read the dropped table's leftover rows | [#99](https://github.com/alberttwong/redis-adbc-driver/pull/99) |
| [#83](https://github.com/alberttwong/redis-adbc-driver/issues/83), [#101](https://github.com/alberttwong/redis-adbc-driver/issues/101) `SUM` / `AVG` of DOUBLE varied with row order and pushdown mode, and gave `NaN` with `aggregate_pushdown=all` on a cluster | [#107](https://github.com/alberttwong/redis-adbc-driver/pull/107) |
| [#84](https://github.com/alberttwong/redis-adbc-driver/issues/84), [#88](https://github.com/alberttwong/redis-adbc-driver/issues/88), [#90](https://github.com/alberttwong/redis-adbc-driver/issues/90) Timestamp text kept trailing zeros; no `AT TIME ZONE` / `convert_timezone()`; `to_char` printed `WW`, `J`, … literally (dbt_utils' `generate_surrogate_key`, dbt_date) | [#97](https://github.com/alberttwong/redis-adbc-driver/pull/97) |
| [#85](https://github.com/alberttwong/redis-adbc-driver/issues/85) Row values, `(k1, k2) IN (…)` (dbt's delete+insert with a list `unique_key`) | [#98](https://github.com/alberttwong/redis-adbc-driver/pull/98) |
| [#86](https://github.com/alberttwong/redis-adbc-driver/issues/86), [#87](https://github.com/alberttwong/redis-adbc-driver/issues/87), [#94](https://github.com/alberttwong/redis-adbc-driver/issues/94) A 5–10 s client read timeout; a killed `rename_rekey` rename blocked retries; incomplete ACL docs | [#100](https://github.com/alberttwong/redis-adbc-driver/pull/100) |
| [#89](https://github.com/alberttwong/redis-adbc-driver/issues/89) Trigonometric functions (dbt_utils' `haversine_distance`) | [#107](https://github.com/alberttwong/redis-adbc-driver/pull/107) |
| [#91](https://github.com/alberttwong/redis-adbc-driver/issues/91), [#92](https://github.com/alberttwong/redis-adbc-driver/issues/92) Multi-action `ALTER TABLE` (`on_schema_change`); `BEGIN` / `COMMIT` / `SET` (hooks outside the transaction) | [#96](https://github.com/alberttwong/redis-adbc-driver/pull/96) |
| [#93](https://github.com/alberttwong/redis-adbc-driver/issues/93) `VARCHAR(n)` / `CHAR(n)` lengths were ignored | [#95](https://github.com/alberttwong/redis-adbc-driver/pull/95) |
| [#102](https://github.com/alberttwong/redis-adbc-driver/issues/102) Wrong results: `t.col` inside `(… from t x …)` read the inner row | [#108](https://github.com/alberttwong/redis-adbc-driver/pull/108) |
| [#103](https://github.com/alberttwong/redis-adbc-driver/issues/103), [#105](https://github.com/alberttwong/redis-adbc-driver/issues/105) Casts to a lower time precision truncated; no session time zone | [#106](https://github.com/alberttwong/redis-adbc-driver/pull/106) |
| [#104](https://github.com/alberttwong/redis-adbc-driver/issues/104) Data loss: `TRUNCATE … RESTART IDENTITY` during a concurrent write | [#109](https://github.com/alberttwong/redis-adbc-driver/pull/109) |
| [#110](https://github.com/alberttwong/redis-adbc-driver/issues/110) Rows whose DOUBLE column is `NaN` were written but never returned | [#116](https://github.com/alberttwong/redis-adbc-driver/pull/116) |
| [#111](https://github.com/alberttwong/redis-adbc-driver/issues/111) Wrong results: schema-qualified column references (`s.t.col`) ignored the schema | [#115](https://github.com/alberttwong/redis-adbc-driver/pull/115) |
| [#112](https://github.com/alberttwong/redis-adbc-driver/issues/112) `GROUP BY` didn't reject ungrouped outer columns inside subqueries | [#117](https://github.com/alberttwong/redis-adbc-driver/pull/117) |
| [#113](https://github.com/alberttwong/redis-adbc-driver/issues/113) Fractional-second precisions other than 0, 3, 6 and 9 snapped to 3, 6 or 9 digits | [#118](https://github.com/alberttwong/redis-adbc-driver/pull/118) |
| [#150](https://github.com/alberttwong/redis-adbc-driver/issues/150) A cancel didn't stop work the driver does in memory (Ctrl-C lagged by a whole join), and was reported as `IO` | [#152](https://github.com/alberttwong/redis-adbc-driver/pull/152) |
| [#151](https://github.com/alberttwong/redis-adbc-driver/issues/151) Seeds (bulk ingest) read timestamps without an offset as UTC in a non-UTC session | [#153](https://github.com/alberttwong/redis-adbc-driver/pull/153) |

dbt's adapter test suite also found these issues:

- [#187](https://github.com/alberttwong/redis-adbc-driver/issues/187): fixed
  by v0.0.16. `UNION` now resolves `DATE` and `TIMESTAMP` together, allowing
  timestamp-strategy snapshots with a `DATE` `updated_at` and hard deletes.
- [#188](https://github.com/alberttwong/redis-adbc-driver/issues/188): fixed
  by v0.0.18. `date(x)` now works, including `dbt_valid_to_current` expressions.
- [#232](https://github.com/alberttwong/redis-adbc-driver/issues/232): fixed
  by v0.0.16. Repeated columns in `DISTINCT` now work, including delete+insert
  with a repeated `unique_key` such as `['state', 'state']`.

The v0.0.16 driver folds unquoted SQL identifiers to lowercase. Quote
mixed-case CSV column names such as `"VendorID"` and `"LocationID"` when
referencing them. Integer literals report `INTEGER`, so model contracts for
expressions such as `select 1 as id` should declare `integer`.

### Known limitations

The driver runs the SQL that dbt and its cross-database macros generate, and
the dbt features above all work. These limits come from the design:

- **No transactions.** Every statement autocommits, so a run that stops in
  the middle of a materialization can leave a `__dbt_tmp` or `__dbt_backup`
  relation behind. dbt drops those at the start of the next run of that
  model. The run's temporary tables (`pg_temp_N`) stay until the driver's
  2-minute heartbeat for that connection runs out; the next connection then
  removes them. Ctrl-C and `--fail-fast` cancel the running statements,
  which leaves the same kind of remains. Each fails with `CANCELLED`: work
  the driver does in memory (a join, say) stops within milliseconds, and a
  Redis command or a streamed `dbt show` result once the reply it waits
  for arrives. A statement that was writing keeps the rows it already
  wrote until the next run drops its relation. A cancelled `rename_rekey`
  rename leaves the table as it was.
- **Python models are tables, and run in the dbt process.** Each ref a
  Python model reads is loaded whole into dbt's memory. Python models can't
  be incremental: dbt's incremental materialization runs only SQL models,
  and says so. dbt runs `dbt show` and unit tests of a Python model as SQL,
  so neither works on any adapter.
- **No materialized views.** `materialized='materialized_view'` stops with
  a clear error.
- **No grants.** Redis controls access per user with ACLs (key patterns and
  commands), not SQL privileges on tables, so a `grants` config is skipped
  with a warning.

## Redis operations

### Access control

dbt can run as a Redis ACL user (`username` / `password` in `profiles.yml`).
The commands and key patterns the driver needs, per feature, and a read-only
user recipe are in the
[driver's README](https://github.com/redis/redis-adbc-driver#server-requirements).
A read-only user can run `dbt show`, the data tests
and `docs generate`. Unit tests and snapshots create temporary tables, which
need `INCRBY` on the driver's metadata keys, so they fail for a read-only
user (dbt reports the unit-test failure as a data-type mismatch).

### Looking at the data in Redis

Each row is a HASH, and each table has a RediSearch index. On a cluster, add
`-c` to `redis-cli` so it follows the key to its shard:

```bash
docker exec redis-dbt-taxi redis-cli HGETALL raw:yellow_tripdata:1
```

```bash
docker exec redis-dbt-taxi redis-cli FT.INFO idx:raw:yellow_tripdata
```

Tables built by dbt's rename-swap keep the row key prefix and index of the
`__dbt_tmp` table they were created as. `ALTER TABLE … RENAME` only changes
metadata, and the driver never gives a new table a prefix another table had
(so a dropped or truncated table's leftover keys can't reach it). Each build's
`__dbt_tmp` therefore gets the next free one: `…__dbt_tmp:`, `…__dbt_tmp~2:`,
`~3` and so on. A table also takes the next names when an index the driver
didn't create already has its index's name (an application's
`idx:taxi:users`, say), and leaves that index and its HASHes alone. To get
keys named after the table, set `rename_rekey: true` in
`profiles.yml`. Each rename then moves the table's rows to keys under its own
name (`schema:table:` on the first build, `schema:table~N:` after that). For a
rebuilt table that costs one copy of its new rows: the adapter drops the old
table instead of moving it to `__dbt_backup` first.
Either way, a table's current prefix and index are in its metadata:

```bash
docker exec redis-dbt-taxi redis-cli GET 'adbc:{meta}:table:taxi_marts:agg_daily_revenue'
```

The metadata also holds the comments `persist_docs` writes. They're easier to
read through `information_schema`:

```bash
uv run dbt show --inline "select table_name, comment from information_schema.tables where table_schema = 'taxi_marts'"
```

To watch the `FT.AGGREGATE` / `HMGET` traffic while dbt runs:

```bash
docker exec -it redis-dbt-taxi redis-cli MONITOR
```

## Data source

NYC TLC yellow taxi trip records for January 2019, as CSV, from the
[DataTalksClub mirror](https://github.com/DataTalksClub/nyc-tlc-data). The TLC
itself now publishes only Parquet. Zone lookup:
[TLC taxi zones](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).
