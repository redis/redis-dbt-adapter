# Model index validation — issue #38

Validated on November 16, 2026 (America/Los_Angeles), through the native
`redis_adbc` adapter and ADBC transport, against an isolated Redis 8.6.2 Docker
instance on macOS arm64. These results do not test dbt-postgres against Redis.

## Revisions and environment

- Adapter: `dbt-redis-adbc` 0.1.0, repository base
  `2f686afc9c301b2219b715bf0405e0395d52ee96` plus this issue's changes to
  `adapter/dbt/adapters/redis_adbc/impl.py` and
  `adapter/dbt/include/redis_adbc/macros/indexes.sql`.
  Source SHA-256 fingerprints for this validation:
  `impl.py`: `81f811d7dd866c18062d203ddd5d46574f9dd6218ae4928a1d18f1f5f8f8db96`;
  `indexes.sql`: `2fdecc7cf6c51a9bf1f57a4536f178e501606611474b24fc2b14e4b9345af289`.
- Driver: latest stable release at validation time,
  [v0.0.27](https://github.com/redis/redis-adbc-driver/releases/tag/v0.0.27),
  tagged source `225e00569986e8340acd5978345f3275a889ade6`.
  Downloaded the published darwin-arm64 library with
  `scripts/download_driver.sh`, which verifies the release SHA-256 sidecar.
- Native library SHA-256:
  `3af17b15fe8fbc81f49616e79a3bed815d2913d98746a880b52295c82d0d9677`.
- Python 3.13.16; locked dbt Core 1.12.6 / dbt-adapters 1.24.5;
  ADBC driver manager 1.12.0; PyArrow 26.0.0.

## Index acceptance

To reproduce on the merged branch, configure a dedicated authenticated TLS
Enterprise test endpoint as described in `../scripts/README.md`, then run from
`v1/`:

```sh
uv sync --locked
./scripts/download_driver.sh
python ../scripts/integration_config.py
uv run pytest adapter/tests/functional/test_indexes.py -q
```

**Result: 16 passed in 15.59 seconds** on the locked dependencies.
The tests invoke real `dbt build` commands, including reruns and
`--full-refresh`, and assert:

- Single-column btree and multi-column hash configuration produces named SQL
  indexes. Both methods are Redis Search compatibility hints.
- `pg_indexes` reports the target table after intermediate-to-target rename;
  `pg_index` reports column counts, column definitions, validity and nonunique
  status. Equality filtering returns the expected row.
- Replacement builds get new SQL names while old names are cleaned up. No
  named indexes remain on intermediate or backup relations. Changing or
  removing a table's index configuration takes effect on rebuild.
- Initial/full-refresh incremental builds create indexes; ordinary incremental
  runs retain them. Both default rename and `rename_rekey: true` are exercised.
- Executing generated `CREATE INDEX IF NOT EXISTS` twice is idempotent;
  repeated `DROP INDEX IF EXISTS` works, and filtering still works afterward.
  Dropping the table removes its remaining named indexes.
- UNIQUE, expressions, partial indexes, unsupported methods, missing columns,
  empty/malformed column lists and malformed index entries produce clear errors.

## Oldest supported dependency check

A separate fresh Redis instance also passed three native CLI builds (initial,
rerun, `--full-refresh`) using dbt Core 1.10.8, dbt-adapters 1.16.0, ADBC driver
manager 1.6.0 and PyArrow 26.0.0 with the same v0.0.27 library. After each build,
ADBC queries asserted two named indexes on the renamed target, expected
filtering results, new SQL names and absence of the retired names. Each dbt
build completed with `PASS=1 WARN=0 ERROR=0`.

Representative final `pg_indexes.indexdef` output:

```sql
CREATE INDEX "dbt_idx_5c3f7c9773b48be4639dec3b58fcc9a9" ON "issue38"."indexed" USING redis_search ("name")
CREATE INDEX "dbt_idx_eebf8e9bd6385fea8069bbd55575a00d" ON "issue38"."indexed" USING redis_search ("id", "name")
```

## Historical compatibility results before merging current main

The latest driver's managed snapshots reject storage initialized by older
formats without modifying it. Validation used a fresh isolated database after
observing that error against the disposable v0.0.20 test storage. This is not an
automatic migration; existing deployments must reload their data into a
compatible fresh database.

On the original base above, the full suite with four pytest workers failed: **93 failed, 56 passed,
26 skipped, 62 errors**. Widespread failures include `snapshot catalog changed
concurrently; retry the statement` (`SQLSTATE 40001`) in setup, seed and model
operations, including tests without index configuration. These results describe the original adapter base, before the safe-publication
retry changes subsequently merged from current main.

A repeat without pytest workers also failed: **37 failed, 167 passed,
26 skipped, 2 errors** in 224.21 seconds. The dbt test profile still uses four
model threads, and catalog conflicts also occur within a single dbt run.
The index tests all passed in this run as well. This is not a claim that the
full adapter suite or parallel model execution was compatible with v0.0.27
on the original base.

The v2 runner unit tests pass (14 tests). The v2 driver pin is updated to match
v1, but the native v2 engine/parity and full NYC taxi project were not rerun here.
Historical v2 validation records retain the versions actually used.

## Integration with current main

Merged repository main `0f762e4a77441eee4c6f9cf25f7166397fe42b0a` into this
branch when preparing the PR. This brings in adapter 0.3.1, safe-publication
retries and the authenticated TLS Enterprise integration policy. The driver
settings retain main's `latest` resolver rather than pinning an older release.
The historical failures above predate those retries. The original native index
results remain evidence for the index implementation; live integration was not
rerun after this merge because no dedicated authenticated TLS Enterprise
endpoint is configured in this session.

After merging main: **28 adapter unit tests passed**, **24 v2 runner tests
passed**, and `git diff --check` passed.

## Source-driver rerun — November 16, 2026

The full functional suite now passes against the newer driver source.

- Adapter revision: `c68a1e0ada9f999203d1cd904d427e59c9203689`
  (`dbt-redis-adbc` 0.3.1, with current main merged).
- Driver revision:
  [`36f456a44fc1af7839e43ab5912a606ad8dadf92`](https://github.com/redis/redis-adbc-driver/commit/36f456a44fc1af7839e43ab5912a606ad8dadf92),
  “Coordinate catalog writes before native statement execution (#451)”.
  This source is newer than published release v0.0.27; the default release
  resolver remains `latest`.
- Built from a clean source checkout with Go 1.27.3, cgo, macOS arm64, using
  `scripts/build_driver.sh` and `DRIVER_VERSION` set to the full commit above.
- Built native library SHA-256:
  `fd94c50379ce75f87ff71ef4c6d0228baf80e339a8a11d665baa04e8fc64caaa`.
- Dedicated Redis Enterprise/Software 8.6.2 RAM database, three primary shards,
  noeviction, verified active 4x QPF and effective Search workers, trusted TLS
  and named-user authentication. Fixture verification passed both before and
  after testing, including rejection of plaintext, untrusted CA and missing or
  incorrect authentication. Existing unrelated containers were left untouched.
- Python 3.13.16, dbt Core 1.12.6, dbt-adapters 1.24.5,
  ADBC driver manager 1.12.0, PyArrow 26.0.0.

After building the driver and loading the dedicated fixture's private
`.redis-enterprise/env.sh`, ran the repository's standard functional command
from `v1/`:

```sh
.venv/bin/pytest -n 4 -q
```

**Result: 206 passed, 28 skipped, zero failures/errors in 152.62 seconds.**
All 16 index tests passed within this full run. The adapter's normal
safe-publication retry behavior was enabled; no test assertions were weakened
and no retry-disabling plugin was used.

The 28 existing skips cover nine materialized-view cases, six array cases,
five general-grant cases, three zero-copy-clone cases, two Flight SQL cases,
one unused catalog-method case, one incremental Python-model case and one
SQL string-escaping case. The separately gated SELECT RBAC integration test was
not enabled because its dedicated role/reader configuration was not provisioned.

Also ran, from the repository root:

```sh
v1/.venv/bin/pytest v1/adapter/tests/unit scripts/tests v1/scripts/tests v2/tests -q
```

**Result: 70 passed and 60 subtests passed**, zero failures. These include the
28 adapter unit tests and 24 v2 runner tests. Unit and functional suites were
invoked separately because pytest rejects the functional suite's nested
`pytest_plugins` declaration when collecting the entire `adapter/tests` parent.

The prior catalog-conflict results above are historical; they were not
reproduced in this source-driver rerun. This does not claim that published
v0.0.27, the full taxi project, the native v2 engine, Flight SQL transport or
the driver's own Go/ADBC validation suites were retested. The dedicated
source-rerun fixture was removed after validation.
