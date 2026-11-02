# dbt v1 Flight SQL validation

Verified locally on November 2, 2026 for [issue #36](https://github.com/redis/redis-dbt-adapter/issues/36).

## Result

The v1 adapter supports the Redis-backed Flight SQL server with
`transport: flightsql`. The default transport remains direct Redis ADBC.
See the [installation and profile example](adapter/README.md#flight-sql).

| Check | Result |
| --- | --- |
| Original `dbt debug`, selecting a Flight library without transport support | Failed: unknown database option `adbc.redis.default_schema` |
| Updated `dbt debug` with `transport: flightsql` | Passed |
| Connection/configuration unit regressions | 13 passed |
| Complete v1 functional suite through Flight SQL | 192 passed, 26 skipped; zero failures/errors |
| Source distribution and wheel build | Passed; wheel includes the `flightsql` extra |
| Dependency lock consistency and whitespace checks | Passed |

The functional suite includes seeds, tables, views, ephemeral models,
incremental strategies, snapshots, contracts, Python models, hooks, tests,
and docs/catalog generation. Additional regressions check temporary-table and
time-zone isolation across Flight connections, plus exact decimal precision,
VARCHAR length, timestamp precision, and column comments. Empty Python-model
results and streamed Arrow model results are exercised by the existing suite.
Skipped tests retain their declared unsupported-feature scope; skips are not
passes. The suite uses disposable schemas and removes them afterward. One schema
left by an earlier aborted diagnostic run was separately removed using that
run's recorded profile names.

## Implementation details

- Flight client database options contain URI, credentials and Flight options;
  Redis-specific settings are rejected with server-configuration guidance.
- Cookie middleware preserves each connection's server session. A small SQL
  query obtains the cookie before setting its quoted schema and time zone.
  An earlier diagnostic using `GetInfo` aborted in the native Flight client
  during repeated threaded tests; the final implementation does not use it.
- Flight `GetObjects` does not provide the Redis SQL type names and comments
  dbt needs. Column metadata is supplemented from `information_schema.columns`,
  preserving declarations such as `NUMERIC(12,2)` rather than guessing from
  Arrow types.
- Empty Arrow ingestion emits an explicit zero-row batch. A schema-only stream
  otherwise fails with `DoPut got no messages` on the tested server/client.
- Driver-option values are redacted from connection diagnostics because Flight
  options may contain bearer tokens or private keys.

## Environment and limits

macOS arm64; Python 3.14.10; dbt Core 1.12.6; ADBC driver manager and Flight SQL
client 1.13.0; PyArrow 26.0.0. The adapter was installed editable from this
checkout into an isolated environment. The original installed adapter used for
the failure reproduction has a connection module byte-identical to this
checkout's baseline.

The existing local `redis-flight-enterprise-test-flight-1` server was used at
`grpc://127.0.0.1:18816`. Its reported vendor version is `dev`; no release or
immutable server build identity is certified here. Its startup log reports
Flight authentication disabled, Flight TLS disabled, sessions enabled, and a
`rediss://` Redis backend. Backend certificate trust, credentials, Redis build
and QPF were not independently requalified by this adapter validation.

Flight TLS/authentication, Linux/Windows, other client/server versions, other
Flight SQL databases, and the full taxi dataset were not tested by this run.
The full direct-Redis suite was not rerun; unit tests verify that native
connection options remain unchanged. No dbt v2 support, SQL transactions,
published package, or merged fix is implied.

## Reproduction

From `v1/`, create an isolated environment and install the adapter plus tests:

```sh
python3.14 -m venv /tmp/dbt-flight-tests
/tmp/dbt-flight-tests/bin/python -m pip install -e './adapter[flightsql]' \
  'dbt-tests-adapter>=1.20,<2' pytest pandas polars
/tmp/dbt-flight-tests/bin/pytest adapter/tests/unit -q
REDIS_ADBC_TRANSPORT=flightsql FLIGHT_SQL_URI=grpc://localhost:8815 \
  DBT_SEND_ANONYMOUS_USAGE_STATS=false \
  /tmp/dbt-flight-tests/bin/pytest adapter/tests/functional -q
```

Provision and export the dedicated Enterprise backend configuration first, as
described in [the environment guide](../scripts/README.md). `REDIS_URI`,
`REDIS_USERNAME` and `REDIS_PASSWORD` continue to describe the authenticated
TLS Redis backend and are required in both test modes.
Use a disposable Redis-backed Flight SQL server with sessions enabled. The
client discovers the Flight library from the optional package; do not set
`REDIS_ADBC_DRIVER` to a native Redis library for these Flight tests. For an
explicit client library, set that variable to the Flight SQL library path.
Use `FLIGHT_SQL_USERNAME`, `FLIGHT_SQL_PASSWORD`, and optionally
`FLIGHT_SQL_TLS_CA_FILE` for the separate Flight client hop.

Local run evidence is retained under `/private/tmp/dbt-flight-verification/`:
`dbt-debug-fixed.log`, `flight-functional.log`, `flight-functional.xml`, and
`build.log`. These temporary artifacts are not versioned or published evidence.
