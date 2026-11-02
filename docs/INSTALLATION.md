# Install the Redis adapter for dbt Core

This guide installs the published Python adapter, configures a Redis connection,
and builds a first model. The commands use the tested combination of
**dbt-redis-adbc 0.2.0**, **Redis ADBC driver 0.0.18**, and **Python 3.13**.

The adapter supports dbt Core 1.10 and later 1.x releases. The experimental
native dbt v2 adapter has its own [engine build and setup guide](../v2/README.md#engine-implementation).

## 1. Check requirements

- Python 3.13, with `venv` and `pip`.
- macOS Apple Silicon, Linux x86-64, or Linux arm64 for the prebuilt native driver.
- A Redis 8.x RAM database with Query Engine (Search) enabled, reachable from
  this machine. Redis Flex is unsupported. See the driver's
  [server requirements and ACL permissions](https://github.com/redis/redis-adbc-driver/blob/main/docs/driver-reference.md#server-requirements).
- A database user allowed to create, read, write, and drop the tables and indexes
  used by the dbt project. The configuration below uses TLS and separate
  username/password credentials.
- `curl`, `tar`, and either `sha256sum` (Linux) or `shasum` (macOS).

The integration test suite uses Redis Enterprise with verified TLS. To create a
local Enterprise test database with generated credentials and a private CA, use
[the local environment guide](../scripts/README.md).

## 2. Install the Python adapter

In a directory where you want to keep your dbt environment:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install dbt-redis-adbc==0.2.0
dbt --version
```

The output should list `redis_adbc: 0.2.0` under plugins. The adapter's dependencies
include dbt Core 1.x, the ADBC driver manager, and PyArrow. You do not need to
clone this repository to use the published adapter.

## 3. Install the native Redis ADBC driver

The adapter package requires a separate native driver shared library. Run this
block in the same shell; it detects your platform, downloads the tested driver
release, verifies its checksum, and sets its absolute library path:

```sh
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLATFORM=darwin-arm64; EXT=dylib ;;
  Linux-x86_64|Linux-amd64) PLATFORM=linux-amd64; EXT=so ;;
  Linux-aarch64|Linux-arm64) PLATFORM=linux-arm64; EXT=so ;;
  *) echo 'No prebuilt driver for this platform; see the driver build guide.'; return 1 2>/dev/null || exit 1 ;;
esac

DRIVER_VERSION=v0.0.18
DRIVER_NAME="adbc_driver_redis-${DRIVER_VERSION}-${PLATFORM}"
DRIVER_DIR="$PWD/redis-driver"
DRIVER_URL="https://github.com/redis/redis-adbc-driver/releases/download/${DRIVER_VERSION}"
mkdir -p "$DRIVER_DIR"
curl -fL "$DRIVER_URL/$DRIVER_NAME.tar.gz" -o "$DRIVER_DIR/$DRIVER_NAME.tar.gz"
curl -fL "$DRIVER_URL/$DRIVER_NAME.tar.gz.sha256" -o "$DRIVER_DIR/$DRIVER_NAME.tar.gz.sha256"
(
  cd "$DRIVER_DIR" || exit 1
  if command -v sha256sum >/dev/null; then
    sha256sum --check "$DRIVER_NAME.tar.gz.sha256"
  else
    shasum -a 256 --check "$DRIVER_NAME.tar.gz.sha256"
  fi
) && tar -xzf "$DRIVER_DIR/$DRIVER_NAME.tar.gz" -C "$DRIVER_DIR"
export REDIS_ADBC_DRIVER="$DRIVER_DIR/$DRIVER_NAME/libadbc_driver_redis.$EXT"
test -f "$REDIS_ADBC_DRIVER" && echo "Driver: $REDIS_ADBC_DRIVER"
```

A successful checksum check prints `OK`. Downloads come from the public
[driver release](https://github.com/redis/redis-adbc-driver/releases/tag/v0.0.18).
Other platforms require a [source build](https://github.com/redis/redis-adbc-driver/blob/main/docs/driver-reference.md#building-and-testing).
Keep `REDIS_ADBC_DRIVER` available when opening a new shell, or export it again
with the absolute path printed above.

## 4. Set connection variables

Use your Redis database endpoint and credentials:

```sh
export REDIS_URI='rediss://redis.example.com:12000/0'
export REDIS_USERNAME='dbt-user'
export REDIS_PASSWORD='<your-password>'
```

For a certificate signed by a private CA, also set its PEM bundle path:

```sh
export REDIS_TLS_CA_FILE='/absolute/path/to/redis-ca.pem'
```

For a certificate trusted by the system, leave `REDIS_TLS_CA_FILE` unset.
The generated local Enterprise environment supplies these variables through
`source .redis-enterprise/env.sh`.

## 5. Add a dbt profile

Create `~/.dbt/profiles.yml`, or add this entry to your existing file:

```yaml
redis_project:
  target: dev
  outputs:
    dev:
      type: redis_adbc
      driver: "{{ env_var('REDIS_ADBC_DRIVER') }}"
      uri: "{{ env_var('REDIS_URI') }}"
      username: "{{ env_var('REDIS_USERNAME') }}"
      password: "{{ env_var('REDIS_PASSWORD') }}"
      driver_options:
        adbc.redis.tls_ca_file: "{{ env_var('REDIS_TLS_CA_FILE', '') }}"
      database: redis
      schema: analytics
      threads: 4
```

Create the `~/.dbt` directory first if needed (`mkdir -p ~/.dbt`). Keep the
credentials in the environment; the profile refers to their variable names.
The `database` value is dbt's logical database name; the URI selects the Redis
endpoint and database number.

## 6. Create and build a first model

Create a minimal project:

```sh
mkdir -p redis-dbt-quickstart/models
cd redis-dbt-quickstart
cat > dbt_project.yml <<'YAML'
name: redis_quickstart
version: '1.0'
config-version: 2
profile: redis_project
model-paths: [models]
models:
  redis_quickstart:
    +materialized: table
YAML
cat > models/hello_redis.sql <<'SQL'
select 1 as id, 'hello from dbt' as message
SQL

dbt debug
dbt build
dbt show --select hello_redis
```

`dbt debug` should report a successful connection. `dbt build` creates the
`hello_redis` table in the `analytics` schema. The preview should contain one
row with `id = 1` and `message = hello from dbt`.

For an existing dbt project, set `profile: redis_project` in its
`dbt_project.yml`, then run the same dbt commands from that project's directory.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `dbt` is missing or `redis_adbc` is absent from `dbt --version` | Activate the environment where you installed `dbt-redis-adbc`; check `python -m pip show dbt-redis-adbc`. |
| The shared library cannot be loaded | Check that `REDIS_ADBC_DRIVER` is an absolute path to the extracted `.dylib` or `.so` for your machine's architecture. |
| TLS certificate verification fails | Use the certificate's hostname in `REDIS_URI` and set `REDIS_TLS_CA_FILE` to the correct private CA bundle where needed. |
| Authentication or permission errors | Check the separate username/password variables and the driver's documented Redis ACL permissions. |
| Query Engine checks fail | Use a Search-enabled RAM database supported by the driver. |

## Next steps

- [Adapter reference](../v1/README.md#adapter-reference): profile fields, materializations, and supported dbt features.
- [NYC taxi example](../v1/README.md#quick-start): seeds, incremental models, snapshots, Python models, and tests.
- [Local Enterprise environment](../scripts/README.md): provision a dedicated TLS test cluster.
- [Release guide](../scripts/RELEASING.md): maintainer instructions for building and publishing adapter releases.
