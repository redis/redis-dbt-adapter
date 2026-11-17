# Redis adapter integration for dbt v2

The pinned engine includes the merged [native Flight SQL implementation](FLIGHT_SQL.md).
[macOS and Linux qualification](../docs/validation/issues70-71-2026-11-16.md)
passes with latest driver main, including deterministic refused-publication and
same-session cancellation probes; the independent stable/main Linux comparison
also passes. Redis and Flight remain experimental in the custom engine. The
broader support qualification stays tracked in #51.

**Adapter source:** [`alberttwong/dbt`](https://github.com/alberttwong/dbt).
The Redis adapter is compiled into that Rust engine. This `v2/` directory
contains the setup guide, profiles, integration fixtures, and validation tools.
Start with [building the tested engine](#engine-implementation), then
[configure a connection and run the smoke checks](#smoke-checks).

**Experimental native Redis support is available in the engine fork.** The
[November 16 qualification](../docs/validation/issue40-2026-11-16.md) passed
smoke, the expanded parity fixture, and the full sampled taxi workflow on
macOS arm64 with dbt-oss 2.0.11, driver v0.0.27, and Redis Enterprise 8.6.2 with
verified TLS/authentication and active QPF 4x. Historical Linux results used
dbt-oss 2.0.8 and driver v0.0.16; see [VALIDATION.md](VALIDATION.md).
The [upstream contribution](https://github.com/dbt-labs/dbt/pull/17195) is pending;
the stock dbt v2 binary does not include Redis. Static analysis remains disabled.

The Python v1 adapter, its dependencies, driver tooling, and NYC taxi example
live in [`../v1/`](../v1/README.md). The v2 runner uses Python 3.13+ and the
standard library only; it does not install or import the v1 adapter.

## Engine implementation

dbt v2 adapters are compiled into the Rust engine, as described in the
[adapter creation guide](https://docs.getdbt.com/guides/adapter-creation-v2).
The engine changes belong in [`alberttwong/dbt`](https://github.com/alberttwong/dbt),
a fork of [`dbt-labs/dbt`](https://github.com/dbt-labs/dbt).
[`upstream.json`](upstream.json) records the source baseline examined for this
work and pins the experimental implementation commit. The connection layer was
merged in [engine PR #1](https://github.com/alberttwong/dbt/pull/1); native profile,
metadata, and SQL execution support is in
[engine PR #2](https://github.com/alberttwong/dbt/pull/2). Broader v1 feature
coverage is in [engine PR #3](https://github.com/alberttwong/dbt/pull/3).
The current pin adds Flight SQL through merged
[engine PR #4](https://github.com/alberttwong/dbt/pull/4).
It includes the public auth-verification documentation correction from
[engine PR #5](https://github.com/alberttwong/dbt/pull/5); that follow-up changes
Markdown only.

```sh
git clone https://github.com/alberttwong/dbt.git redis-dbt-engine
cd redis-dbt-engine
git remote add upstream https://github.com/dbt-labs/dbt.git
git checkout 1988196900588c1be955b7b0cc87cd956fa47539
# Requires the checkout's Rust toolchain, a C/C++ toolchain, and protoc.
cargo build -p dbt-sa-cli
# Executable: target/debug/dbt
```

Read that checkout's `AGENTS.md`, `.agents/adapters.md`, and `CONTRIBUTING.md`
before making engine changes. Its architecture has evolved from some paths in
the public adapter guide; use the pinned source as the implementation reference.
For auth/profile changes, the [public verification guide](AUTH_VERIFICATION.md)
provides runnable native Redis and Flight probes and the human review record;
the public engine fork does not contain a `dbt-auth-tests` crate.

The integration work is tracked in
[issue #27](https://github.com/redis/redis-dbt-adapter/issues/27).
This directory replaces the need for a separate `redis-dbt-v2-adapter` integration
repository. That repository remains empty.

## Smoke checks

Pass the **v2 executable explicitly**. Do not pass `v1/.venv/bin/dbt`, which is
Python Core 1.x. From this repository's root:

```sh
# Parse only; no Redis connection or driver download is performed by the runner.
python3 v2/smoke.py --dbt /absolute/path/to/dbt-v2

# Use a Redis-enabled engine build and a dedicated Redis Enterprise test cluster.
export REDIS_ADBC_DRIVER=/absolute/path/to/libadbc_driver_redis.dylib
export REDIS_URI=rediss://your-enterprise-endpoint:port/0
export REDIS_USERNAME=your-test-user
export REDIS_PASSWORD='<your-test-password>'
# Debug engine builds require trace spans; a restrictive RUST_LOG can panic.
RUST_LOG=trace python3 v2/smoke.py --dbt /absolute/path/to/dbt-v2 --build
```

Use the appropriate `.so` or `.dll` on other platforms. Use `REDIS_USERNAME` and
`REDIS_PASSWORD` for credentials; they are not command arguments. The driver
library is distributed separately. The existing `v1/scripts/download_driver.sh`
can fetch it into `v1/driver/` using the existing GitHub access requirements.
Keep `REDIS_ADBC_DRIVER` absolute because the runner copies the fixture to a
temporary directory. The [v1 driver guide](../v1/README.md#requirements) describes
server and driver requirements. The fork accepts `driver`, `uri`, `username`,
`password`, `database` (only `redis`), `schema`, `threads`, and `time_zone`.
The parity implementation additionally accepts `aggregate_pushdown`,
`rename_rekey`, `read_timeout`, `write_timeout`, and scalar `driver_options`.
Reserved connection options cannot be overridden through `driver_options`.

The runner checks the executable's major version, then parses using
`type: redis_adbc`. It fails on an unregistered adapter rather than substituting
another warehouse. For `--build`, it creates a random `dbt_v2_smoke_*` schema,
performs a full-refresh build followed by an incremental build, checks fresh
`run_results.json` artifacts, and drops only its own schema afterward. A failed
build still attempts cleanup; cleanup failure returns a failure and prints the
schema name for manual removal. Temporary project files, logs, and artifacts
are removed when the runner exits. dbt output is streamed to the console.

The fixture covers seed loading, an ephemeral model, a table, a view, generic
tests, and incremental `delete+insert`. Three seed rows must remain three rows
after both builds, and totals must reconcile. It has no package dependencies,
does not download taxi data, and does not use the v1 taxi schemas.

The runner enables `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=yes` for an experimental
Redis engine build. This does not register a missing adapter.

## Validation scope and remaining work

The locked v1 dependencies include a `dbt-core-experimental-parser` executable
reporting `dbt-oss 2.0.5`. On the unmodified engine it rejects the fixture with
`unknown variant redis_adbc` while loading `profiles.yml`, before parsing models
or connecting to Redis. The `dbt parse --use-v2-parser` path has the same blocker.
Simply relaxing the v1 `<2` dependency constraints cannot fix this.

Run the runner unit tests without a database:

```sh
python3 -m unittest discover -s v2/tests -v
```

CI runs those unit tests separately from the v1 functional suite. The manual
native workflow builds the pinned engine and can run the smoke, feature-parity,
TLS, and full taxi suites. [Linux verification passed on October 21, 2026](https://github.com/alberttwong/redis-dbt-adapter-with-project/actions/runs/39623533131).
Redis stays experimental and static analysis is disabled.

The current candidate is pinned on engine branch `codex/redis-adbc-upstream`.
Its direct-Redis base is submitted as
[upstream PR #17195](https://github.com/dbt-labs/dbt/pull/17195); the additional
Flight implementation is merged in the engine fork's PR #4.
The earlier feature-parity milestone was merged in engine PR #3. The current
[API audit and qualification](../docs/validation/issue40-2026-11-16.md) retain
source-specific results; upstream review and CI approval remain separate.

v2 reports ephemeral nodes as `skipped` in `run_results.json`, even when its CLI
calls them no-ops. The runner accepts this only for `trips_input`; every seed,
materialized model, and test must still succeed on both builds. The engine
expands seed bindings into SQL literals, so it uses the default `%s` macro
placeholder instead of the driver's native prepared-statement `?` placeholder.

See the [implementation checklist](IMPLEMENTATION.md) for remaining work.
The [integration status](../docs/integration-status.md) separates the historical
fork validation from upstream contribution work and tracks remaining
Flight SQL qualification work under issue #40.

## Feature-parity checks

Python models and the custom CSV loader use a local Python subprocess with
PyArrow 26 and the ADBC driver manager on Python 3.13+. They do not import the
Python dbt adapter.
The executable uses `python3` from `PATH`; install model-specific packages in
that environment yourself. `dbt.ref()` and `dbt.source()` return Arrow tables,
`session.sql()` returns an Arrow table, and model results can be Arrow tables,
record batches/readers, pandas DataFrames, or polars DataFrames. As in v1,
Python models are tables only. Python execution is not supported in replay mode.

```sh
python3.13 -m venv .venv-v2
.venv-v2/bin/python -m pip install -r v2/requirements-python.txt
export PATH="$PWD/.venv-v2/bin:$PATH"
export REDIS_ADBC_DRIVER=/absolute/path/to/libadbc_driver_redis.dylib
export REDIS_URI=rediss://your-enterprise-endpoint:port/0
export REDIS_USERNAME=your-test-user
export REDIS_PASSWORD='<your-test-password>'
RUST_LOG=trace python3 v2/parity.py --dbt /absolute/path/to/dbt-v2
RUST_LOG=trace python3 v2/taxi.py --dbt /absolute/path/to/dbt-v2 \
  --csv "$PWD/v1/data/yellow_tripdata_2019-01.csv.gz"
```

Use the latest stable Redis ADBC release from `redis/redis-adbc-driver`.
The current candidate was qualified with v0.0.27, including enforced primary
key, unique, and foreign key constraints; record the release resolved for each run.
Upgrades from older driver storage formats require a fresh, isolated Redis
database and reloading the data; there is no automatic storage migration.
Historical results in `VALIDATION.md` retain their actual versions.
Build the engine with its default
features (`cargo build -p dbt-sa-cli`) so docs generation has the embedded UI.
For a JSON warehouse catalog, request `dbt build --write-catalog`; v2's docs
command exports its index and does not always produce the legacy JSON catalog.

Both runners create random schemas and clean only their own namespace. The taxi
runner copies the current v1 SQL project, quotes seed headers, and moves the raw
loader/source into its generated namespace. It leaves v1 files and data intact.
Add `--keep-artifacts` to retain logs and artifacts for debugging. The CSV
runner supports gzip, stable file row IDs, stride sampling, and row limits; it
validates the sampled input before replacing an existing table. Loading is
memory-bound, matching v1's sampled-table behavior.

All live integration checks require a Redis Enterprise cluster with TLS,
`REDIS_USERNAME`, and `REDIS_PASSWORD`. The runners reject plaintext URIs,
missing credentials, and `skip_verify` bypasses before invoking dbt. Certificates must be trusted. For a private CA, set `REDIS_TLS_CA_FILE`
to its PEM bundle; the profiles pass it as `adbc.redis.tls_ca_file`. This
works with the native macOS verifier as well as Linux. The native workflow provisions a dedicated three-shard Enterprise cluster
with TLS and a named user on its runner, then exports verified connection
settings with the generated password masked. No database secrets are required.
For external test endpoints, provision an Enterprise database with Search; the
scripts validate connection settings, while the operator provisions the cluster.
Parse-only checks and mocked unit tests need no database.
