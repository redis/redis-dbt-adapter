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
