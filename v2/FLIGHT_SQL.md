# Native v2 Flight SQL candidate

This is an experimental implementation for [#51](https://github.com/redis/redis-dbt-adapter/issues/51),
included in the merged engine commit pinned by [upstream.json](upstream.json).
Both direct Redis and Flight SQL are compiled into that engine; no patch is
needed for a fresh checkout. The historical [engine patch](engine/flight-sql.patch)
is retained to reproduce earlier evidence. Broader native v2 Flight support
qualification remains in #51.
After [Flight PR #75](https://github.com/redis/redis-apache-arrow-flight/pull/75)
resolved the session reset in #74, full local qualification passes with both
latest driver main and latest stable v0.0.27. The
[qualification receipt](../docs/validation/issue51-2026-11-16.md) preserves the
original failure and the subsequent passing runs separately.

## Build and install

Read the engine checkout's `AGENTS.md`, `.agents/adapters.md` and contributing
instructions. Check out the merged pin in a clean engine repository, then build:

```sh
cd /path/to/dbt-engine
git checkout 3f285a37312c6ccab44a16b71d831c49e35417bd
cargo build -p dbt-sa-cli
```

The patch contains the Rust profile, authentication, driver selection, connection
session handling, exact type supplementation, bounded refusal retry handling,
optional local runtime changes, tests and a generated changelog. It adds no Rust
dependencies and does not change engine macros. The actual engine source was submitted in
[engine PR #4](https://github.com/alberttwong/dbt/pull/4) at
`667707f32b746359d74affa477144418ed2a0179`, stacked on the pinned Redis
branch, and merged as `3f285a37312c6ccab44a16b71d831c49e35417bd`.
The global integration pin now selects that merged commit. Its entire Git tree
is identical to the qualified source commit `667707f32b746359d74affa477144418ed2a0179`.
`apply_engine_patch.py` verifies the clean merged checkout without modifying it;
it still supports the historical patch base recorded in `upstream.json` for
reproduction. Automated validation does not establish human auth verification.

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
merged at `3671fca7894240551d19aeb196d7b7362f8869d2`. The post-Flight-#74
qualification covers that driver commit; the original receipts retain their
pre-fix driver revision. The compatibility lookup remains for older drivers.

## Reproduce qualification

For focused auth/profile review of an engine under development, use the
[public auth verification guide](AUTH_VERIFICATION.md). Its probes do not
require the checkout's HEAD to equal this integration's immutable engine pin.

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
The [manual Linux workflow](../.github/workflows/v2-flight.yml) uploads receipts
and defaults to latest driver `main`; select `compare_stable` for
an additional independently rebuilt stable comparison. Every invocation resolves
and records the actual driver commit, even when using a moving source ref.

### Deterministic refusal and cancellation probes

The qualifier places a loopback TLS proxy between its owned Flight server and
the dedicated Redis backend. For selected publication workspaces, it executes
the driver's real seal operation and returns CAS refusal only after a successful
seal. The real driver exhausts its metadata rebase attempts and returns the
Flight refusal envelope; SQL and Flight responses are never mocked. All other
Redis traffic, including authentication, is forwarded. Do not use this fault
fixture with a shared database.

`refusal.json` records publication/rebase counts and attempt timing without
workspace identifiers or credentials. The checks require a successful native
retry with preserved session settings/temporary data, exactly 20 attempts on
persistent refusal, and no replay of a script's committed first statement when
its second statement exhausts retries. The actual optional engine Arrow runtime
is imported separately to test empty and nonempty retained tables, the 20-attempt
bound, and a caller-provided one-shot reader that must receive just one attempt.
The owned schema must be dropped after both successful and failed checks.

`session-cancellation.json` supplements native CLI SIGINT with a Python ADBC
Flight protocol probe. It observes an active query lease in Redis, cancels a
partially consumed result stream, checks time zone and temporary data on the
same connection, and requires all newly created query leases to become inactive
within ten seconds. It does not establish native engine pool reuse after global
CLI interruption, nor measure all server memory, Search cursors, or file handles.

## Boundaries and remaining work

- The candidate remains autocommit-only; it adds no transactions, rollback,
  generic Flight database support, or replay-mode Python execution.
- Optional Python/CSV ingestion is tested separately. Retained Arrow tables
  can provide a fresh input reader after an explicit publication refusal.
  Caller-provided one-shot readers, unknown outcomes and cancellation are
  never replayed. Retry attempts are bounded at 20.
- Full current-source and stable v0.0.27 local runs passed with Flight server
  `e4dcbd37322536f73ef923e0ab4b76a1abf3d4dc`, including the strict session
  audit that failed on the older server. This is bounded local evidence,
  not proof of every conflict schedule or deployment.
- Deterministic native Flight refusal and same-session protocol cancellation
  probes now pass on macOS and Linux with latest driver main; see the
  [new evidence](../docs/validation/issues70-71-2026-11-16.md).
  Broader native cancellation/resource coverage remains part of
  [#51](https://github.com/redis/redis-dbt-adapter/issues/51). The missing public
  auth live-test suite is replaced in the public instructions by the runnable
  [auth verification guide](AUTH_VERIFICATION.md), correcting
  [#74](https://github.com/redis/redis-dbt-adapter/issues/74). Automated probes
  do not establish that a human ran a live-test suite. The reproduced
  optional-runtime failure and merged fix are recorded in closed
  [#71](https://github.com/redis/redis-dbt-adapter/issues/71).
