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

To stop the fixture without deleting its state:

```sh
docker stop redis-dbt-enterprise
```

To reset the fixture, including expired certificates, first remove its owned
container (`docker rm -f redis-dbt-enterprise`), then remove `.redis-enterprise/`
and rerun `up`. This deletes the fixture's test data and generated credentials.

CI provisions the same Enterprise fixture separately on every integration
runner, including each matrix entry. `up --github-env` masks the generated
password and exports the verified URI, username, password, CA path, and driver
path through `GITHUB_ENV`. No preconfigured database secrets or external test
cluster are required. The native v2 workflow uses the same setup.
