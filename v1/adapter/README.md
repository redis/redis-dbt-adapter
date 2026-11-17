# dbt-redis-adbc

A dbt Core adapter for Redis 8.x, built on the
[Redis ADBC driver](https://github.com/redis/redis-adbc-driver).
Compatible with dbt Core 1.10 and later 1.x releases.

## Install

Requires Python 3.13 or later (PyArrow 26+) and Redis 8.x with the Query Engine (Search)
enabled. The adapter is tested against Redis 8.6.2.

```shell
python -m pip install dbt-redis-adbc
```

The Python package does not include the native Redis ADBC driver. Download and
extract the shared library for your platform from the
[driver releases](https://github.com/redis/redis-adbc-driver/releases).
The example project uses driver v0.0.27. Prebuilt libraries are available for
macOS Apple Silicon, Linux x86-64, and Linux arm64.

Set `REDIS_ADBC_DRIVER` to the library's absolute path. See the driver's
[server requirements and ACL permissions](https://github.com/redis/redis-adbc-driver#server-requirements)
before connecting.

## Configure

Set your dbt project's `profile` to `redis_project` and add this profile to
`~/.dbt/profiles.yml`:

```yaml
redis_project:
  target: dev
  outputs:
    dev:
      type: redis_adbc
      driver: "{{ env_var('REDIS_ADBC_DRIVER') }}"
      uri: "{{ env_var('REDIS_URI', 'redis://localhost:6379/0') }}"
      username: "{{ env_var('REDIS_USERNAME', '') }}"
      password: "{{ env_var('REDIS_PASSWORD', '') }}"
      database: redis
      schema: analytics
      threads: 4
```

Use a `rediss://` URI for TLS. Keep credentials in the separate username and
password fields. From your project, verify the connection with:

```shell
dbt debug --profile redis_project
```

## Model indexes

Configure named, nonunique Redis Search indexes on table models:

```sql
{{ config(materialized='table',
          indexes=[{'columns': ['name'], 'type': 'btree'},
                   {'columns': ['id', 'name'], 'type': 'hash'}]) }}
select 1 as id, 'one' as name
```

`columns` must be a non-empty list of existing column names, with exact case.
Column names are quoted as identifiers. `type` defaults to `btree`; `btree` and
`hash` are compatibility hints backed by Redis Search, not PostgreSQL storage
methods. `unique: false` is accepted. UNIQUE, expression and partial indexes,
other methods, and unknown options raise a compilation error.

The adapter emits `CREATE INDEX IF NOT EXISTS` with generated `dbt_idx_…` names.
Names include the dbt invocation so a replacement table can build its indexes
before the previous target is retired. Indexes follow the intermediate table's
rename to the target, appear in `pg_indexes` / `pg_index`, and their SQL names
are removed when the old table is dropped. A table rebuild applies the current
configuration; an incremental model creates indexes on its initial build or
`--full-refresh`, and keeps them on ordinary incremental runs. Use
`--full-refresh` to change an incremental model's indexes. Views do not create
indexes.

The driver normally indexes supported columns already; this config additionally
registers SQL names and requests indexing for the listed columns. Dropping a
named SQL index forgets its name but retains shared physical Search fields.

Use the latest stable driver release (currently v0.0.27). Its managed storage
requires a fresh, isolated database when moving from older storage formats;
existing storage is rejected without modification. Rebuild models and reload
sources into the new database; there is no automatic storage migration.
See the [driver snapshot guide](https://github.com/redis/redis-adbc-driver/blob/v0.0.27/docs/snapshots.md).

[Issue #38 validation](../INDEXES_VALIDATION.md) records the tested revisions and
actual native ADBC run results.

## Features and limitations

- Tables, views, ephemeral models, Arrow bulk-loaded seeds, and snapshots
- SQL incremental models with `append`, `delete+insert`, `merge`, and `microbatch`
- Model contracts, persisted relation and column descriptions, and Python table models
- No SQL transactions or rollback: statements autocommit, and interrupted writes
  may need cleanup or a rerun
- No materialized views or SQL grants; configure access with Redis ACLs
- Python models run in the dbt process and load their inputs into its memory;
  incremental Python models are not supported

See the [adapter reference](https://github.com/redis/redis-dbt-adapter/blob/main/v1/README.md#adapter-reference)
for all profile options, supported features, and limitations. The
[example project and functional tests](https://github.com/redis/redis-dbt-adapter/tree/main/v1)
demonstrate the adapter with NYC taxi data.
