# Redis adapters for dbt

**[Documentation website](https://redis.github.io/redis-dbt-adapter/)**

**[Installation guide: install the adapter, native driver, and build your first model](docs/INSTALLATION.md)**

## Install the dbt Core adapter

Install the published adapter in a Python 3.13 environment:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install dbt-redis-adbc==0.2.0
dbt --version
```

Then follow the [installation guide](docs/INSTALLATION.md) to install the separate
native Redis ADBC driver, configure your Redis TLS connection and dbt profile,
and run a first model. You need Redis 8.x with Query Engine (Search) enabled.
The published Python package supports dbt Core 1.10 and later 1.x releases.

## Repository guides

This repository keeps dbt v1 and v2 work together, with separate dependencies,
projects, and test resources.

| Directory | Purpose | Status |
| --- | --- | --- |
| [`v1/`](v1/README.md) | Python `dbt-redis-adbc` adapter, NYC taxi example, driver tooling, and functional tests | Supports dbt Core 1.10 and later 1.x releases; the example requires 1.10.8+ |
| [`v2/`](v2/README.md) | Native v2 fixtures, taxi validation, and tooling | Experimental fork: smoke and v1 feature scenarios pass on macOS and Linux; requires a custom engine |

## Run the v1 example

All integration tests use a dedicated Redis Enterprise cluster with TLS and
username/password authentication. To create a local Enterprise test cluster,
run `python3 scripts/redis_enterprise.py up` and
`source .redis-enterprise/env.sh` from the repository root; see the
[environment guide](scripts/README.md). For an existing Enterprise cluster,
run the commands from `v1/`:

```sh
cd v1
export REDIS_URI=rediss://your-enterprise-endpoint:port/0
export REDIS_USERNAME=your-test-user
export REDIS_PASSWORD='<your-test-password>'
make setup
make all
```

See the [v1 guide](v1/README.md) for connection configuration, requirements,
supported features, and the NYC taxi demos. The installable adapter package is
in [`v1/adapter/`](v1/adapter/README.md). If you had a virtual environment from
the former root layout, recreate it from `v1/` with `uv sync --reinstall` and
refresh local package links with `uv run dbt deps`.

## Use Redis with dbt v2

**The Redis dbt v2 adapter is implemented in the
[`alberttwong/dbt` engine fork](https://github.com/alberttwong/dbt).** Its engine
changes are merged, and the supported v1 compatibility scenarios pass on macOS
and Linux, including the NYC taxi project, Python models, snapshots,
microbatch, and trusted TLS.

- **Get the adapter:** build the Redis-enabled engine from the tested source
  commit listed in [`v2/upstream.json`](v2/upstream.json), following the
  [v2 setup guide](v2/README.md#engine-implementation).
- **Configure and run it:** follow the [connection and smoke instructions](v2/README.md#smoke-checks)
  and [full-project validation commands](v2/README.md#feature-parity-checks).
- **Check coverage and limitations:** see the [validation results](v2/VALIDATION.md).

The adapter is compiled into that engine; the standard dbt v2 executable does
not include Redis, and installing the v1 Python package does not add it. Redis
support remains experimental in the custom engine.

This repository's [`v2/`](v2/README.md) directory contains integration fixtures,
configuration examples, and test runners. The Rust adapter implementation lives
in the engine fork. Development history is tracked in
[issue #27](https://github.com/redis/redis-dbt-adapter/issues/27).

## Publishing releases

See the [release guide](scripts/RELEASING.md) for PyPI trusted publishing setup
and the tag-based build, test, and publication workflow.
