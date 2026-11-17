# Remaining adapter contract coverage

Work on issues [#52](https://github.com/redis/redis-dbt-adapter/issues/52),
[#53](https://github.com/redis/redis-dbt-adapter/issues/53),
[#54](https://github.com/redis/redis-dbt-adapter/issues/54),
[#55](https://github.com/redis/redis-dbt-adapter/issues/55),
[#56](https://github.com/redis/redis-dbt-adapter/issues/56), and
[#57](https://github.com/redis/redis-dbt-adapter/issues/57).

## Implemented behavior

- **SELECT grants:** the generic grants suite mixed supported table SELECT grants
  with unsupported INSERT/view privileges. Its five blanket skips are replaced by
  five dedicated integration cases: table, seed, incremental, snapshot, and invalid
  privilege/role/object checks. Two owned reader roles verify access, grantee
  changes, revocation, idempotent reruns and full-refresh replacement where applicable.
  The fixture requires a dedicated single-database Software cluster with verified
  management TLS, backend TLS and active 4× QPF. It obtains the canonical reader
  policy from the checksummed driver CLI, changes only its owned role bindings,
  and uses a cleanup stack to remove users, bindings, ACLs and roles on failure.
  Native CI runs these cases serially after ordinary adapter tests and fails if
  its required management fixture is absent. General INSERT/view grants remain
  unsupported; the adapter rejects them explicitly.
- **Clone:** a missing-state negative test now runs without requiring zero-copy
  support. Same-source/target full refresh preserves the source instead of building
  a self-referencing view. The adapter validates state/target-directory identity.
  Active fallback and capability tests establish that native zero-copy cloning
  remains false; no copied table/view is relabeled zero-copy.
- **Flight SQL:** extend the existing authenticated public-source qualification
  workflow from PR #65 rather than introducing another deployment path. The two
  original session/metadata cases and a real dbt build/rerun/data-test/catalog
  case run with `transport: flightsql`. The separate security suite verifies
  trusted TLS/login, missing and wrong credentials, untrusted certificates,
  concurrent isolated sessions recovering after failure, and plaintext rejection.
  The public build helper pins the committed server source, resolves the latest
  stable Redis driver, and records both revisions and the executable SHA-256.
  The workflow runs the security and full functional suites and retains sanitized
  version/JUnit artifacts. Native-only conditional transport skips are not
  represented as missing driver features.
- **Python incremental:** execute Python once into a permanent dbt intermediate
  table, then apply append, delete+insert or merge using native SQL. The default
  follows the SQL adapter (delete+insert with a unique key, append otherwise).
  Initial build/full refresh constructs a replacement before renaming the target.
  Arrow record-batch readers are ingested once. Standard schema-change policies,
  hooks, docs, grants and initial/full-refresh indexes are retained. Unsupported
  strategies, merge without a unique key and enforced Python incremental contracts
  are rejected explicitly. Python exceptions and schema-policy failures preserve
  the prior published target; later builds clean stale intermediates. Statements
  still autocommit: no rollback of arbitrary Python/session side effects, atomic
  multi-statement rename/index sequence, or automatic replay of Python is promised.
- **Strings:** replace a foreign-dialect plain literal with active standard SQL
  doubled-quote/literal-backslash and explicit `E'...'` tests, including mixed
  characters, empty strings and lengths. The driver's plain-string semantics are
  unchanged.
- **Single-relation catalog:** return dbt's `CatalogTable` using ADBC metadata and
  table comments, with exact catalog/schema/name filtering, column order, exact
  types/precision and descriptions. Missing relations return `None`. Seed/view
  inherited fixtures now have real expectations; additional table/materialized-view
  and quoted-name cases execute.

## Reproduce

Native functional tests use the existing authenticated Software fixture:

```sh
python3 scripts/redis_enterprise.py up --github-env  # in GitHub Actions
cd v1
uv sync --locked
make driver
uv run pytest adapter/tests/functional -n 4 -q
REDIS_REQUIRE_RBAC_TESTS=1 REDIS_ADBC_DRIVER="$PWD/driver/libadbc_driver_redis.so" \
  uv run pytest adapter/tests/integration/test_native_select_contract.py -q
```

For local management overrides, supply `REDIS_RBAC_API_URL`,
`REDIS_RBAC_API_USERNAME`, `REDIS_RBAC_API_PASSWORD`, and
`REDIS_RBAC_API_CA_FILE`. `REDIS_ADBC_CLI` can identify a matching driver CLI;
otherwise the fixture downloads and verifies the resolved release's archive.
Do not run two RBAC provisioning suites against the same cluster concurrently.
For source qualification, resolve and record an immutable driver SHA, build
with `DRIVER_VERSION=<sha> make driver-build`, and build its matching CLI with
`make -C build/redis-adbc-driver/go adbc-cli VERSION=<sha>`. Set
`REDIS_ADBC_CLI` to that checkout's `go/build/redis-adbc` executable. Run native,
RBAC, oldest-runtime and Flight qualification serially on a shared backend.

Authenticated Flight qualification uses the public builder and workflow in
`.github/workflows/flight-sql.yml`:

```sh
python3 scripts/build_flight_server.py --source /path/to/committed/flight \
  --output /private/path/redis-flight-server
# Start that server with redis-acl auth, verified backend TLS, TLS certificate/key
# and sessions enabled. For source QA, pass `--driver-ref` with the immutable
# driver SHA above. Export FLIGHT_SQL_URI, FLIGHT_SQL_USERNAME,
# FLIGHT_SQL_PASSWORD and FLIGHT_SQL_TLS_CA_FILE for the independent client hop.
cd v1
uv sync --locked
uv pip install adbc-driver-flightsql==1.13.0 adbc-driver-manager==1.13.0
FLIGHT_SQL_SECURITY_TESTS=1 .venv/bin/python -m pytest adapter/tests/integration/test_flight_security.py -q
REDIS_ADBC_TRANSPORT=flightsql .venv/bin/python -m pytest adapter/tests/functional -n 4 -q
```

The server's committed source revision is
`4d91e37135080be7f0eeb770fc89fa7adeb14bc8`; the helper independently resolves
and records the resolved driver revision on each build. No private feature composition or
unpublished security implementation is required. Credentials, private keys,
endpoints and raw operational logs are not published.

## Validation results

Validation date: November 16, 2026 (America/Los_Angeles), macOS arm64.
The backend was dedicated Redis Software 8.8.0 with three active primary shards,
authenticated TLS, noeviction, active 4× QPF, six Search workers, mnp routing
and 32 connections. Both management and data certificates were verified.

| Scope | Result |
| --- | --- |
| Native full functional suite, latest source `640dbf1` | 228 passed, 3 Flight-only skips, zero failures/errors (139.75 s) |
| Native SELECT grants, latest source `640dbf1` | 5 passed, including build/tests/catalog, real reader access and teardown (90.60 s) |
| Latest-source Flight full suite | 227 passed, 4 native-only skips, zero failures/errors (189.43 s) |
| Latest-source focused Flight transport/security | 9 passed, zero skips/failures/errors (6.68 s) |
| Earlier public authenticated Flight full suite, v0.0.27 | 227 passed, 4 skipped, zero failures/errors (220.53 s) |
| Earlier focused Flight transport/security, v0.0.27 | 9 passed, zero skips (18.99 s) |
| Unit tests, including management conflict/unknown-outcome regression | 44 passed |
| Oldest supported dbt runtime, latest driver source | Seed/build, Python incremental rerun/full refresh, docs, single/missing catalog API, self-target clone, tests and cleanup passed |
| Strict MkDocs build and whitespace checks | Passed |

The native locked runtime uses Python 3.13.16, dbt Core 1.12.6,
dbt-adapters 1.24.5, dbt-tests-adapter 1.20.0, PyArrow 26.0.0 and
ADBC driver manager 1.12.0. The Flight client uses the same Python/dbt/Arrow
tuple with Flight SQL client and driver manager both 1.13.0. The oldest
runtime uses Core 1.10.8, adapters 1.16.0, manager 1.6.0 and PyArrow 26.0.0.

Final source qualification uses freshly built driver main
`640dbf1fa8809fb9e12e761c4edd11373a4233f1`, as requested. Its Darwin arm64
native library SHA-256 is
`142f396712bb3e6205589f26f0db080f913533c5e5cb571f12f5df554e782412`.
The matching CLI is built from the same checkout. The public Flight executable
is rebuilt against that source driver (`v0.0.0-20261117055145-640dbf1fa880`),
SHA-256 `ae5abf16cd94aa4d2447d426d5c9a54cabc8beacfd6bc66626de359add86e888`.
After the source grants suite, verified management API reads confirmed zero
owned test users, roles and ACLs remain.
The helper accepts `--driver-ref` and the workflow accepts the equivalent manual
input, while their default remains latest stable.

Earlier stable v0.0.27 qualification resolves to driver commit
`225e00569986e8340acd5978345f3275a889ade6`. The tested Darwin arm64 native
library SHA-256 is
`3af17b15fe8fbc81f49616e79a3bed815d2913d98746a880b52295c82d0d9677`.
The earlier public Flight server was built from committed source
`4d91e37135080be7f0eeb770fc89fa7adeb14bc8`, linked to that same stable driver
(`v0.0.0-20261115214919-225e00569986`), using Go 1.27.3. Its executable SHA-256 is
`1190e287e87df2186d8cdb0d1b0f62b3a7655f27705ff35c05072d39c6559617`.
An initial full v0.0.27 native attempt recorded 227 passes, three transport skips
and one failure when the driver refused admission at its 16-generation snapshot
limit. The oldest-runtime commands passed in that overlapping run, but their
raw cleanup hit a concurrent-catalog conflict. The follow-up isolated stable run
was interrupted at the request to qualify latest source. No broader adapter
replay rule was added to suppress these errors.

These results qualify the recorded tuples; the hosted workflow rebuilds and retains its
own provenance and JUnit results. Local results do not imply hosted CI success.
The disposable local Flight server was stopped after qualification. The native
SELECT fixtures and oldest-runtime schema were removed successfully.

### Skip accounting and upstream scope

The original 13 exclusions are replaced by five native grant cases, active
clone/state/fallback coverage, three Flight functional cases, Python incremental
lifecycle tests, valid string semantics, and single-relation catalog checks.
`TestClonePossible.test_can_clone_true` is intentionally not collected because
Redis reports no native zero-copy capability. An active false-capability
assertion and actual fallback/read/state tests replace that inapplicable claim.
The inherited fallback capability assertion is not collected a second time in
the self-target subclass. These are explicit capability exclusions, not newly
implemented zero-copy support.

A native-only suite conditionally skips these three Flight cases:

- `TestFlightSessions.test_temporary_tables_and_settings_are_connection_local`
- `TestFlightColumnMetadata.test_sql_types_precision_and_comments`
- `TestFlightBuildAndCatalog.test_build_rerun_and_catalog`

The Flight suite executes all three, and instead skips the four native-only
rename/rekey cases scoped by PR #68:

- `TestIndexesRenameRekey.test_build_rebuild_and_cleanup[table]`
- `TestIndexesRenameRekey.test_build_rebuild_and_cleanup[incremental]`
- `TestIndexesRenameRekey.test_if_not_exists_and_drop`
- `TestIndexesRenameRekey.test_replace_configuration`

The Flight workflow now checks the JUnit files and fails if fewer than three
transport cases or six security cases execute, or if any required case skips or
fails. Native CI separately requires the provisioned SELECT suite.

Generic dbt issues found during this work are filed upstream:
[catalog fixture mismatch #2333](https://github.com/dbt-labs/dbt-adapters/issues/2333),
[clone fixture decorators #2334](https://github.com/dbt-labs/dbt-adapters/issues/2334),
and [self-target fallback guard #2335](https://github.com/dbt-labs/dbt-adapters/issues/2335).
Redis-specific Arrow staging, metadata mapping and SELECT ACL provisioning
remain in this adapter. Native dbt v2 work is separately tracked; no new driver
feature request is needed for these six items.
