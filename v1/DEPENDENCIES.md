# Dependency upgrade notes

## November 17, 2026 refresh

Refreshed `uv.lock` against PyPI with `uv lock --upgrade`: 24 existing packages
updated, including dbt Core 1.12.7, dbt adapters 1.24.6, ADBC driver manager
1.13.0, PyArrow 26.0.1, pandas 3.1.1, Polars 2.1.0, and pytest 9.2.0. The
optional v2 requirements pin the same Arrow and ADBC versions. Hatchling now
requires 1.33.0; setup-uv is pinned to 10.3.3. The other GitHub Actions use
current major tags, and dbt_utils 1.4.1 and pip-audit 2.10.1 remain current.

The driver defaults retain main's `latest` policy, which currently resolves to
[v0.0.29](https://github.com/redis/redis-adbc-driver/releases/tag/v0.0.29). It
includes the concurrent first-open fix from
[driver PR #468](https://github.com/redis/redis-adbc-driver/pull/468). Source
builds require Go 1.27.4+. When a release exists before its assets are uploaded,
the downloader now recognizes GitHub CLI's `no assets to download` response
and uses the existing source-build fallback.

The driver's own Python wheel now requires Python 3.14+. This project instead
loads the native shared library through `adbc-driver-manager`; it does not
install `adbc-driver-redis`. The supported runtime remains Python 3.14+, matching current main. The older
Python 3.13 results below are historical evidence from before rebasing. Storage protocol 17 still requires compatible stored data; historical
formats have no automatic migration or safe-downgrade guarantee. Use fresh data
when moving from the older driver pin. The native engine commit remains pinned:
it contains the custom Redis adapter, which a stock dbt binary cannot replace.

The earlier v0.0.28 candidate had one parallel setup failure on a fresh Redis
8.10.3 database (189 passes and 26 skips). A stale catalog-presence read made
startup reject another opener's successful initialization as incompatible
storage. The fix rechecks the catalog format and permissions, preserving
legacy-data refusals and unknown-reply errors. It passed deterministic
regressions and 10 race-detector runs before merging. No adapter retry policy
was added.

Adapter cursor cleanup now uses the ADBC context manager in metadata queries,
Python-model reads, and bulk ingest. Metadata Arrow readers also close
explicitly through their context manager. The connection-level cursor tracker
remains necessary because dbt leaves some cursors open and ADBC requires
statements to close before their connection. The table materialization,
CSV sampling, and SQL macro overrides still provide Redis-specific behavior
that the current upstream defaults do not cover.

### Flight build toolchain

The pinned Flight sources declare Go 1.27.3, while the current driver requires
Go 1.27.4. Both Flight qualification workflows explicitly select Go 1.27.4;
using only the Flight go.mod selects an insufficient toolchain when
`GOTOOLCHAIN=local`. The v1 qualification source (`4d91e3713508`) built
successfully against driver v0.0.29 with Go 1.27.4 and automatic toolchain
switching disabled. The build evidence recorded driver commit `30a9eefbf13d`
and the expected selected toolchain.

### Validation after rebasing onto current main

The final branch preserves Python 3.14+, adapter version 0.3.2, the latest-driver
resolvers, and the current native/Flight engine configuration. With Python
3.14.10 and the v0.0.29 source-built library, 40 native adapter tests passed
(basic materializations/catalogs, Python models, persisted documentation and
concurrency) on the dedicated authenticated TLS Redis Software 8.8.0 fixture
with verified active 4x QPF and noeviction.

All 44 adapter unit tests, 59 v2 runner tests, 14 root script tests and 9 v1
script tests passed. Locked Python dependency audits reported no known
vulnerabilities, and the 0.3.2 wheel/source builds, shell syntax, lockfile check
and lint for the two modified workflows passed. Full-repository actionlint also
reports existing SC2035 glob warnings in the unchanged publish workflow.
Flight integration, compiled native v2 parity and the full taxi-data workflow
were not rerun on the rebased branch. Earlier integration results follow with
their original runtime and scope.

### Validation before rebasing onto current main

The v0.0.29 source-build fallback checked out release commit
`30a9eefbf13d19b3e3129171f8ecdc5579b852a2` and built the native library with
Go 1.27.4. ADBC GetInfo reported `v0.0.29`. Release assets were still being
published during this run, so this evidence qualifies the tagged source build,
not the packaged release binaries.

On macOS arm64 with Python 3.13.16, the full adapter suite passed 190 tests with
26 expected skips against Redis Software 8.8.0 (one shard, TLS/password,
noeviction, verified active 4x QPF). On a fresh Redis Open Source 8.10.3
instance, basic/concurrency/Python-model tests passed 25 tests with 2 expected
skips using four workers. The pytest warning filter now also matches pytest
9.2's plural wording for the upstream suite's fixture deprecation.

An isolated oldest-dependency environment (dbt Core 1.10.8, dbt adapters
1.16.0, ADBC manager 1.6.0, PyArrow 26.0.0) loaded all four seeds and built
all four seed-backed staging views with v0.0.29 on Redis Open Source 8.10.3.
The 14 v2 runner unit tests, actionlint, shell syntax checks and `uv lock --check`
passed. The earlier wheel/source builds and Python requirement audits also
passed; pip-audit reported no known vulnerabilities in either Python
requirements set. The compiled native v2 engine parity and full taxi-data
workflows were not rerun locally.

## October 22 runtime baseline

The October 22, 2026 refresh for [issue #29](https://github.com/redis/redis-dbt-adapter/issues/29)
uses PyArrow 26.0.0 in both Python runtimes and Polars 2.0.0 in the adapter test
suite. Python 3.14 is the minimum supported version. The example uses
Python 3.14 (`>=3.14,<3.15`); the adapter package requires Python 3.14 or later.
Support for Python 3.13 and earlier has been dropped to standardize the runtime and
remove older-Python dependency resolutions. Recreate environments with Python
3.14 before running `uv sync --locked`.

## Security updates

The adapter requires `opentelemetry-api>=1.45.2`, and the example locks 1.45.2,
to address [CVE-2026-126360](https://github.com/advisories/GHSA-mf5v-w3w3-f6cg).
This fixes denial of service from quadratic-time parsing of malformed
`traceparent` values in dbt's transitive OpenTelemetry dependency.

## Compatibility changes

[PyArrow 26](https://arrow.apache.org/blog/2026/10/08/26.0.0-release/) drops
Python 3.10 and requires NumPy 2.x and pandas 2.2.2+ for their optional
integrations. The example's development dependencies now require pandas 3 and pytest 9,
matching their current major versions. The Arrow-only native v2 runtime still needs only PyArrow and the
ADBC driver manager. The oldest-dependency CI lane now uses PyArrow 26.0.0,
with dbt Core 1.12.0, dbt-adapters 1.24.5, Mashumaro 3.17, and ADBC manager 1.6.0.
Python 3.14 requires the newer dbt floors: older dbt versions cap Mashumaro
below 3.15, which fails during import on Python 3.14. The adapter explicitly
requires Mashumaro 3.17 or later so dependency resolution cannot select an
incompatible older version.

[Polars 2](https://docs.pola.rs/releases/upgrade/2/) changes lazy collection to
use the streaming engine by default. The adapter retains normal Polars
collection behavior and converts the result with `to_arrow()`. Its existing
functional Python-model tests exercise lazy Polars results, pandas results,
Arrow tables/readers, empty results, and table replacement. Native v2 parity
also exercises Arrow Python models and the CSV loader against the pinned
engine and driver.

## Remaining upstream constraints

These constraints were rechecked against PyPI release metadata on November 17,
2026. The lockfile selects the newest releases allowed by the current dbt
packages and supported Python versions. Do not override upstream requirements
to force these upgrades; recheck when dbt publishes compatible releases.
The installed dependency metadata still excludes the newer releases listed
below; upgrading them requires compatible upstream dbt releases. All direct
dependencies resolve to their latest stable releases on Python 3.14.

| Library | Locked version | Latest stable | Reason retained |
| --- | --- | --- | --- |
| agate | 1.9.1 | 1.14.2 | dbt-common 1.39.0 requires `<1.10` |
| DeepDiff | 8.6.2 | 9.1.0 | dbt-common 1.39.0 requires `<9.0` |
| mashumaro | 3.17 | 3.23 | dbt-core 1.12.7 and dbt-adapters 1.24.6 require `<3.18` |
| more-itertools | 10.8.0 | 11.2.1 | metricflow 0.214.0 requires `<11.0` |
| pathspec | 1.0.4 | 1.1.1 | dbt-core 1.12.7 and dbt-common 1.39.0 require `<1.1` |
| protobuf | 6.33.6 | 7.36.2 | dbt-adapters 1.24.6 and dbt-common 1.39.0 require `<7.0` |
| python-dateutil | 2.9.0.post0 | 4.0.0 | dbt-common requires `<3.0`; metricflow requires `<2.10` |

Sources: [dbt-common metadata](https://pypi.org/pypi/dbt-common/1.39.0/json),
[dbt-core metadata](https://pypi.org/pypi/dbt-core/1.12.7/json),
[dbt-adapters metadata](https://pypi.org/pypi/dbt-adapters/1.24.6/json),
and [MetricFlow metadata](https://pypi.org/pypi/metricflow/0.214.0/json).

NetworkX 3.7 and NumPy 2.5.5 now resolve uniformly to their latest stable
versions; older-Python fallback versions are no longer needed.

CI audits the locked runtime and development dependencies and the optional
native v2 requirements. The Redis driver and native dbt engine are pinned in
`v2/upstream.json`; their source changes belong in their respective repositories.
