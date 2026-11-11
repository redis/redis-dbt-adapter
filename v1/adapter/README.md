# dbt-redis-adbc

A dbt Core adapter for Redis 8.x, built on the
[Redis ADBC driver](https://github.com/redis/redis-adbc-driver).
Compatible with dbt Core 1.10 and later 1.x releases.

**[Complete installation and first-model guide](https://github.com/redis/redis-dbt-adapter/blob/main/docs/INSTALLATION.md)**
covers Python installation, native driver download and checksum verification,
TLS configuration, a dbt profile, and your first model.

## Install

Requires Python 3.13 or later (PyArrow 26+) and Redis 8.x with the Query Engine (Search)
enabled. Integration tests require a Redis Enterprise cluster with TLS and
username/password authentication.

```shell
python -m pip install dbt-redis-adbc==0.3.0
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
      uri: "{{ env_var('REDIS_URI') }}"
      username: "{{ env_var('REDIS_USERNAME', '') }}"
      password: "{{ env_var('REDIS_PASSWORD', '') }}"
      driver_options:
        adbc.redis.tls_ca_file: "{{ env_var('REDIS_TLS_CA_FILE', '') }}"
      database: redis
      schema: analytics
      threads: 4
```

Use a `rediss://` URI for TLS. Keep credentials in the separate username and
password fields. For a private CA, set `REDIS_TLS_CA_FILE` to its PEM bundle's
absolute path. From your project, verify the connection with:

```shell
dbt debug --profile redis_project
```

### Flight SQL

To use a separately deployed [Redis Arrow Flight server](https://github.com/redis/redis-apache-arrow-flight),
install the Flight client extra:

```shell
python -m pip install 'dbt-redis-adbc[flightsql]'
```

```yaml
redis_project:
  target: flight
  outputs:
    flight:
      type: redis_adbc
      transport: flightsql
      uri: "{{ env_var('FLIGHT_SQL_URI', 'grpc://localhost:8815') }}"
      username: "{{ env_var('FLIGHT_SQL_USERNAME', '') }}"
      password: "{{ env_var('FLIGHT_SQL_PASSWORD', '') }}"
      database: redis
      schema: analytics
      time_zone: UTC
      threads: 4
```

The client loads `adbc_driver_flightsql` automatically; an explicit `driver`
can point to a Flight SQL shared library instead. `REDIS_ADBC_DRIVER` applies
only to the default `transport: redis`. The server loads Redis ADBC and needs
Redis with Search. This mode targets the Redis-backed Flight SQL server,
rather than arbitrary Flight SQL databases.

Enable sessions on the server and route each connection to the same server
process. The adapter enables Flight cookie middleware and sets schema/time zone
in each connection's SQL session, preserving temporary tables across requests.
Configure `aggregate_pushdown`, `rename_rekey`, Redis read/write timeouts and
other `adbc.redis.*` options on the server; the client rejects those settings.
`driver_options` accepts Flight client options, including TLS root certificates
and RPC timeouts. Cookie middleware cannot be disabled.

For TLS use `grpc+tls://` and configure certificate trust in the Flight client;
username/password refer to the server's Flight authentication. Available TLS
and authentication features depend on the server build. Follow its
[deployment guide](https://github.com/redis/redis-apache-arrow-flight/blob/main/docs/server-guide.md).
No SQL transactions are introduced by this transport. dbt v2 is separate.
See the [local validation record](../FLIGHT_SQL_VALIDATION.md) for tested
versions, workflow coverage, and deployment limits.

## Features and limitations

- Tables, views, ephemeral models, Arrow bulk-loaded seeds, and snapshots
- SQL incremental models with `append`, `delete+insert`, `merge`, and `microbatch`
- Model contracts, persisted relation and column descriptions, and Python table models
- No SQL transactions or rollback: statements autocommit, and interrupted writes
  may need cleanup or a rerun
- Native SQL statements and in-memory Arrow tables retry a refused snapshot
  catalog publication up to nineteen times with backoff. Scripts execute one statement
  at a time so committed statements are not replayed. Arrow record batch readers
  are captured once in a temporary disk file to supply fresh input on retry. Bound
  SQL input, unknown stream types, Flight SQL, and unknown publication outcomes
  are not automatically replayed.
- No materialized views. Native SELECT grants can opt into dedicated Redis Software ACLs; see [SQL grants](../README.md#sql-grants-through-dedicated-redis-software-acls).
- Python models run in the dbt process and load their inputs into its memory;
  incremental Python models are not supported

See the [adapter reference](https://github.com/redis/redis-dbt-adapter/blob/main/v1/README.md#adapter-reference)
for all profile options, supported features, and limitations. The
[example project and functional tests](https://github.com/redis/redis-dbt-adapter/tree/main/v1)
demonstrate the adapter with NYC taxi data.
