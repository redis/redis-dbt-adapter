# Native v2 Flight SQL candidate

This is an experimental implementation for [#51](https://github.com/redis/redis-dbt-adapter/issues/51),
supplied as a reviewable [engine patch](engine/flight-sql.patch) against the
native engine commit in [upstream.json](upstream.json). The default engine pin
still supports direct Redis only. **Native v2 Flight support is not advertised:**
stable-release qualification found a session reset tracked in
[Flight #74](https://github.com/redis/redis-apache-arrow-flight/issues/74).
The [qualification receipt](../docs/validation/issue51-2026-11-16.md) distinguishes
current driver source from stable-release results.

## Build and install

Read the engine checkout's `AGENTS.md`, `.agents/adapters.md` and contributing
instructions. From this integration repository, apply the patch to a clean
engine checkout at `754f0a47164f86226dc568096ac56906ff9d2e69`:

```sh
python3 v2/apply_engine_patch.py --engine /path/to/dbt-engine
cd /path/to/dbt-engine
cargo build -p dbt-sa-cli
```

The patch contains the Rust profile, authentication, driver selection, connection
session handling, exact type supplementation, bounded refusal retry handling,
optional local runtime changes, tests and a generated changelog. It adds no Rust
dependencies and does not change engine macros. It has not been committed or
merged into the engine fork. Its auth input changes require human verification
before committing, under that checkout's `crates/dbt-auth/AGENTS.md`.

Install the separate Apache ADBC Flight client library:

```sh
python3.13 -m venv .venv-flight
.venv-flight/bin/python -m pip install -r v2/requirements-flight.txt
export PATH="$PWD/.venv-flight/bin:$PATH"
export FLIGHT_SQL_DRIVER="$(python -c 'import adbc_driver_flightsql; print(adbc_driver_flightsql._driver_path())')"
```

This environment also supplies the optional Python-model/CSV runtime. It does
not install the v1 Python dbt adapter. The compiled Rust adapter loads the
Flight library directly; Python is not involved in native SQL execution.

## Separate server deployment and connection contract

Deploy the Redis-backed Flight SQL server separately, with sessions enabled,
`--auth redis-acl`, verified client TLS, and trusted authenticated TLS to Redis.
[The deployment guide](../scripts/README.md#flight-sql-qualification) describes
building it with a freshly resolved Redis driver. Changing a URI alone does
not select Flight in a native Redis profile.

The candidate accepts `transport: redis` (the default) or `transport: flightsql`.
For Flight, use the [separate profile](flight_profiles.yml):

```yaml
type: redis_adbc
transport: flightsql
driver: /absolute/path/to/libadbc_driver_flightsql.so
uri: "{{ env_var('FLIGHT_SQL_URI') }}"
username: "{{ env_var('FLIGHT_SQL_USERNAME') }}"
password: "{{ env_var('FLIGHT_SQL_PASSWORD') }}"
tls_ca_file: "{{ env_var('FLIGHT_SQL_TLS_CA_FILE') }}"
database: redis
schema: analytics
threads: 4
time_zone: America/New_York
```

Use the installed library's platform-specific filename, including `.so` on
platforms where the Python wheel uses that suffix. The path must be absolute.
The URI must use `grpc+tls://host:port`; embedded credentials, query parameters
and non-root paths are rejected. Credentials stay out of the target context.
`tls_ca_file` supplies PEM roots; omission uses client/system trust. There is no
TLS verification bypass in this contract.

`driver_options` accepts only nonnegative finite values for the Flight RPC
timeout options ending in `connect`, `fetch`, `query` and `update`, under
`adbc.flight.sql.rpc.timeout_seconds.`. Cookie middleware is mandatory and
cannot be disabled. Arbitrary headers, bearer tokens, mTLS private keys and
other client options are outside this initial contract. This prevents secret
options from reaching generic driver diagnostics.

Configure `aggregate_pushdown`, `rename_rekey`, Redis read/write timeouts and
all `adbc.redis.*` options on the Flight server. The client rejects them.
The existing direct Redis profile mapping remains available.

Each client connection bootstraps its server cookie, then sets schema and time
zone. Pool keys include those settings and the library path. Unused query
results are drained without retaining rows, preserving connection-local state.
Redis information-schema declarations supplement physical Arrow table schemas
for exact VARCHAR lengths and temporal/decimal types; docs/catalog already use
Redis metadata. [Driver #453](https://github.com/redis/redis-adbc-driver/issues/453)
was resolved by [driver PR #454](https://github.com/redis/redis-adbc-driver/pull/454),
merged at `3671fca7894240551d19aeb196d7b7362f8869d2` after the recorded
qualification. The compatibility lookup remains for older drivers; the receipts
retain the actual pre-fix driver revision and do not qualify that new commit.

## Reproduce qualification

Provision and independently verify the dedicated Enterprise backend first;
export its `REDIS_URI`, `REDIS_USERNAME`, `REDIS_PASSWORD`, and
`REDIS_TLS_CA_FILE`. Export separate `FLIGHT_SQL_USERNAME`,
`FLIGHT_SQL_PASSWORD`, and `FLIGHT_SQL_TLS_CA_FILE`. The supplied certificate
must cover `127.0.0.1`, which the runner binds for its owned Flight process.
Do not place credentials in command arguments or evidence JSON.

```sh
RUST_LOG=trace python v2/qualify_flight.py \
  --dbt /path/to/dbt-engine/target/debug/dbt \
  --engine-source /path/to/dbt-engine \
  --server-source /path/to/redis-apache-arrow-flight \
  --tls-cert /path/to/server.crt --tls-key /path/to/server.key \
  --backend-evidence /path/to/sanitized-backend-versions.json \
  --output-dir /path/to/new-evidence-directory --driver-ref main
```

`--driver-ref main` resolves and builds latest Redis ADBC source on each
invocation. Omit it for a separate latest-stable-release run. Both build a fresh
server from immutable committed Flight source; neither reuses an old server
binary. Requires Git, GitHub CLI access, Go, make, Rust, OpenSSL and the engine's
native build tools. Backend evidence is a sanitized JSON record of independent
topology/TLS/auth checks and Redis/version information; without it the receipt
does not establish the backend's deployment identity.

The runner retains resolved source and runtime versions, binary and source
digests, the patch, dependency lock, CLI logs, cancellation result and parity
artifacts. It stops its own server on success or failure. Fixtures create/drop
random owned schemas. A failing assertion remains a failed qualification.
The [manual Linux workflow](../.github/workflows/v2-flight.yml) runs stable and
main separately and uploads receipts; it has not yet been executed for this
candidate.

## Boundaries and remaining work

- The candidate remains autocommit-only; it adds no transactions, rollback,
  generic Flight database support, or replay-mode Python execution.
- Optional Python/CSV ingestion is tested separately. Retained Arrow tables
  can provide a fresh input reader after an explicit publication refusal.
  Caller-provided one-shot readers, unknown outcomes and cancellation are
  never replayed. Retry attempts are bounded at 20.
- A full current-source local run passed. Stable v0.0.27 passed security,
  smoke and parity after the empty-upload fix, but failed strict session
  isolation. Passing main does not prove all conflict schedules preserve state.
- Linux execution, deterministic native Flight refusal injection, deeper
  same-session cancellation/resource checks and engine human review remain in
  [project #70](https://github.com/redis/redis-dbt-adapter/issues/70).
  The reproduced optional-runtime failure and candidate fix are tracked in
  [#71](https://github.com/redis/redis-dbt-adapter/issues/71).
