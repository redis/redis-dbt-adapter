# Public Redis and Flight authentication verification

The public engine fork does not contain `crates/dbt-auth-tests`. Use the commands
below for Redis/Flight profile changes. They exercise the compiled native engine,
not the Python v1 adapter. Other providers need their own live fixtures; these
commands do not qualify cloud-provider authentication.

A human must review compatibility-sensitive auth changes. Automated execution is
evidence for that review and must not be recorded as a human approval or human-run
test. Keep the five-part impact report and review record at the end of this guide.

## Prepare the engine and dedicated fixture

From the engine checkout under review:

```sh
cargo test -p dbt-auth --lib redis_adbc
cargo test -p dbt-schemas --lib redis_adbc_tests
cargo build -p dbt-sa-cli
```

These unit tests check profile mapping, scalar compatibility, reserved options,
Flight URI/option restrictions and credential redaction. The ignored
`live_driver_query` test is a basic native query probe; it does not supply the
profile's CA option and is not the trusted-TLS acceptance command below.

In a separate clone of [redis/redis-dbt-adapter](https://github.com/redis/redis-dbt-adapter),
from its root, prepare the isolated Enterprise fixture and driver:

```sh
python3 scripts/redis_enterprise.py up
source .redis-enterprise/env.sh
python3 scripts/redis_enterprise.py verify
bash v1/scripts/download_driver.sh
```

Docker, OpenSSL, Python 3.13+, the GitHub CLI and the engine's build tools are
required. The native driver downloader uses latest stable by default. To test
latest source instead, build the resolved driver revision explicitly and set
`REDIS_ADBC_DRIVER` to that absolute library path; retain the actual source SHA.
The fixture's CA, passwords and keys stay in `.redis-enterprise/`. Follow the
[restart/reset instructions](../scripts/README.md#restarting-the-fixture) if its
saved CA no longer matches a restarted container.

Set the executable under review, using its absolute path:

```sh
export DBT_ENGINE=/absolute/path/to/engine/target/debug/dbt
export RUST_LOG=trace
```

Debug engine builds require trace spans. The driver library path must also be
absolute. Do not enable TLS verification bypasses to make a probe pass.

## Direct Redis client

```sh
python3 v2/flight_security.py --transport redis --dbt "$DBT_ENGINE"
```

Despite its historical filename, this command uses the direct Redis profile
when `--transport redis` is selected. It requires only Python's standard library
in the runner and the native Redis ADBC library. It checks:

| Case | Required result |
| --- | --- |
| Named username/password with the fixture's CA | Native CLI succeeds |
| Wrong credentials embedded in URI with valid explicit fields | Explicit username/password take precedence; succeeds |
| Wrong explicit password | Native client rejects authentication, with an auth diagnostic |
| Valid but unrelated CA | Native client rejects the certificate chain |
| CLI output | Configured passwords do not appear |
| No-fetch query followed by temporary-table query | Connection-local state is retained |
| CLI interruption and subsequent fresh invocation | Bounded cancellation is reported; fresh authenticated invocation succeeds |

The fixture's independent `verify` command additionally checks rejected
plaintext, missing auth and incorrect passwords, plus verified TLS, Search,
read/write/delete and the expected Enterprise topology. These backend checks
complement the native-client profile checks.

## Flight SQL client

Install the separate Flight client/runtime environment and use the deployment
instructions in [FLIGHT_SQL.md](FLIGHT_SQL.md). For a fixture-backed local server,
build a committed public Flight source checkout and run it in a second terminal:

```sh
python3 scripts/build_flight_server.py --source /absolute/path/to/flight-source \
  --output /tmp/auth-review-flight-server --driver-ref main
/tmp/auth-review-flight-server --listen 127.0.0.1:18841 --auth redis-acl \
  --sessions=true --tls-cert "$PWD/.redis-enterprise/server.crt" \
  --tls-key "$PWD/.redis-enterprise/server.key" \
  --adbc-option "adbc.redis.tls_ca_file=$REDIS_TLS_CA_FILE"
```

That terminal must retain the exported `REDIS_*` fixture environment. The build
helper resolves driver main to an immutable SHA and writes a version/digest
receipt beside the executable. The development fixture's certificate covers
`127.0.0.1`; an external deployment needs a certificate for its actual hostname.

In the review terminal, retain the same backend configuration and export the
separate client hop:

```sh
python3.13 -m venv .venv-flight
.venv-flight/bin/python -m pip install -r v2/requirements-flight.txt
export PATH="$PWD/.venv-flight/bin:$PATH"
export FLIGHT_SQL_URI=grpc+tls://127.0.0.1:18841
export FLIGHT_SQL_USERNAME="$REDIS_USERNAME"
export FLIGHT_SQL_PASSWORD="$REDIS_PASSWORD"
export FLIGHT_SQL_TLS_CA_FILE="$REDIS_TLS_CA_FILE"
export FLIGHT_SQL_DRIVER="$(python -c 'import adbc_driver_flightsql; print(adbc_driver_flightsql._driver_path())')"
python v2/flight_security.py --transport flightsql --dbt "$DBT_ENGINE"
```

The probe checks accepted/rejected credentials, trusted/untrusted CA, password
redaction, no-fetch temporary-state preservation and bounded CLI cancellation
with fresh-connection recovery. Engine profile tests additionally reject
plaintext or credential-bearing Flight URIs, server-side Redis options, secret
headers and attempts to disable cookie middleware. The client credentials and
trust are separate from server-to-Redis configuration; URI credentials are not
accepted for the Flight client. Stop the owned Flight server after the review.

This command accepts a compiled engine under review without requiring its HEAD
to equal the integration pin. For immutable-pin qualification, concurrency,
refusal injection and same-session cancellation assessment, use the complete
[qualification runner](FLIGHT_SQL.md#reproduce-qualification), which checks source
identity. CLI interruption alone does not prove reuse of an interrupted native
pool connection or exhaustive server-resource cleanup.

## Impact report and human review record

Before asking for review of auth-code changes, explicitly report:

1. Whether existing borrowed fields became owned, and why any new ownership is
   required at an external boundary.
2. Whether `get_string`/`get_str` behavior or accepted scalar shapes changed.
3. Which accepted profile/input shapes changed, including TLS and client options.
4. Whether auth enum structure changed and how the auth family is classified.
5. Whether normalization/coercion changed or existing compatibility is preserved.

When any of these changes, preserve the engine instruction: **Human verification
is required before committing this change.** Ask the human reviewer to run the
applicable public probes above. Do not count skipped, unconfigured or unavailable
provider cases as passing.

Use this record in the review/PR; leave human fields unfilled until supplied by
the actual reviewer:

```text
Engine commit and integration tooling commit:
Driver revision, Flight client/server versions, OS and Rust/Python versions:
Auth impact report (all five points):
Execution actor: human / automation (identify accurately)
Commands and exit statuses; expected negative cases observed:
Sanitized log/version receipt locations:
Unrun or unavailable cases and their reason:
Human reviewer:
Human review decision, date and scope:
```

Check retained output for credentials and private keys before sharing it. A
maintainer merge, automated green run, or completed template is not itself proof
that a human ran a particular live test.
