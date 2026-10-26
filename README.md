# Redis adapters for dbt

This repository keeps dbt v1 and v2 work together, with separate dependencies,
projects, and test resources.

| Directory | Purpose | Status |
| --- | --- | --- |
| [`v1/`](v1/README.md) | Python `dbt-redis-adbc` adapter, NYC taxi example, driver tooling, and functional tests | Supports dbt Core 1.10 and later 1.x releases; the example requires 1.10.8+ |
| [`v2/`](v2/README.md) | Native v2 fixtures, taxi validation, and tooling | Experimental fork: smoke and v1 feature scenarios pass on macOS and Linux; requires a custom engine |

## Run the v1 example

Run the existing commands from `v1/`:

```sh
cd v1
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
