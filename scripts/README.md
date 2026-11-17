# Local Redis Enterprise integration environment

From the repository root:

```sh
python3 scripts/redis_enterprise.py up
source .redis-enterprise/env.sh
cd v1
make setup
make adapter-tests
```

Requires Docker, OpenSSL, Python 3, and `uv` for the dbt runtime. This creates a
dedicated `redis-dbt-enterprise` container from `redislabs/redis:8.2.0-78.18`.
It uses the built-in development trial. The cluster has one Enterprise node
and a three-shard Redis 8.6 RAM database with Search and QPF 4x. Its 2 GiB
database limit allows full refreshes to retain an old table while building its
replacement during the taxi demos. It is a local
test cluster without replication, not an HA deployment.

Only localhost ports are published:

| Purpose | Endpoint |
| --- | --- |
| Database, TLS only | `rediss://localhost:16380/0` |
| Enterprise management API | `https://localhost:19444/v1` |

The setup creates a named database user with a randomly generated password
and a separate randomly generated administrator password. The database user
has full Redis permissions in this isolated test database and no management
permissions. Credentials and private certificate keys live in the private,
git-ignored `.redis-enterprise/` directory. Do not commit or share `env.sh` or
`credentials.json`.

The generated CA signs localhost certificates valid for 30 days. `env.sh` sets
`REDIS_TLS_CA_FILE`, which the profiles pass as `adbc.redis.tls_ca_file`, so
the ADBC driver trusts that CA on macOS and Linux without a TLS verification
bypass or a global trust-store change. It also sets `REDIS_URI`,
`REDIS_USERNAME`, `REDIS_PASSWORD`, and the absolute pinned driver path.
Only the initial owned loopback management bootstrap uses the container's
unverified self-signed certificate; subsequent API and data connections verify
the generated CA and hostname.

Run `python3 scripts/redis_enterprise.py verify` to recheck Enterprise topology,
TLS, authentication, Search, write/read/delete, and rejection of plaintext,
untrusted certificates, missing authentication, and incorrect passwords.
`up` can restart/reuse this checkout's existing container. It refuses a container
with the same name owned by another checkout. Existing unrelated Enterprise
containers are left alone.

## Restarting the fixture

To stop the fixture:

```sh
docker stop redis-dbt-enterprise
```

Run `up` again to reuse the fixture if its cluster state and certificate survive.
The `verified-api` marker does not guarantee that a restarted container retained
them. If management TLS no longer trusts the saved CA, `up` fails immediately
with reset instructions. It does not retry with certificate verification disabled
or send credentials over an unverified connection to recover an initialized fixture.
Temporary connection failures while services start still retry normally.

## Resetting the fixture

To reset a stale fixture, including expired certificates, first remove its owned
container (`docker rm -f redis-dbt-enterprise`), then remove `.redis-enterprise/`
and rerun `up`. This deletes the fixture's test data and generated credentials.

CI provisions the same Enterprise fixture separately on every integration
runner, including each matrix entry. `up --github-env` masks the generated
password and exports the verified URI, username, password, CA path, and driver
path through `GITHUB_ENV`. No preconfigured database secrets or external test
cluster are required. The native v2 workflow uses the same setup.

## Flight SQL qualification

Build a committed public Flight server checkout with the **latest stable Redis
ADBC driver release** on each invocation:

```sh
python3 scripts/build_flight_server.py --source /path/to/redis-apache-arrow-flight \
  --output /tmp/dbt-flight-server
```

The source checkout is left intact. The helper builds in a temporary directory
and writes `/tmp/dbt-flight-server.json` with the source commit, resolved driver
release/commit, Go module version, toolchain, and binary SHA-256. Keep that
resolved evidence with the validation result; do not substitute an older driver
pin for the latest-release build policy.

Run the server on loopback using `--auth redis-acl`, `--tls-cert`, `--tls-key`,
and `--adbc-option adbc.redis.tls_ca_file="$REDIS_TLS_CA_FILE"`. Its `REDIS_URI`
must point to the verified Enterprise fixture above. Use a certificate valid
for the Flight hostname and trust its CA on the client. Sessions must be enabled.

Export `FLIGHT_SQL_URI=grpc+tls://localhost:<port>`, `FLIGHT_SQL_USERNAME`,
`FLIGHT_SQL_PASSWORD`, and `FLIGHT_SQL_TLS_CA_FILE` for this separate client hop.
Install `v1/adapter[flightsql]` and the project's development dependencies, then:

```sh
cd v1
FLIGHT_SQL_SECURITY_TESTS=1 .venv/bin/python -m pytest \
  adapter/tests/integration/test_flight_security.py -q
env -u REDIS_ADBC_DRIVER REDIS_ADBC_TRANSPORT=flightsql \
  .venv/bin/python -m pytest adapter/tests/functional -q
```

Retain the `REDIS_*` backend environment in both modes. The security probes
check verified Flight TLS, accepted/rejected credentials, untrusted certificate
rejection, and isolated concurrent sessions recovering after a failed statement.
The functional suite supplies actual dbt workflow coverage. Use private logs
for diagnosis; publish only evidence checked for credentials and private keys.
