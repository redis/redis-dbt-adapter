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
The example project uses driver v0.0.18. Prebuilt libraries are available for
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
