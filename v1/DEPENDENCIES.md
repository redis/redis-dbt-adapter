# Dependency upgrade notes

The October 22, 2026 refresh for [issue #29](https://github.com/redis/redis-dbt-adapter/issues/29)
uses PyArrow 26.0.0 in both Python runtimes and Polars 2.0.0 in the adapter test
suite. Python 3.13 is now the minimum supported version. The example uses
Python 3.13 (`>=3.13,<3.14`); the adapter package requires Python 3.13 or later.
Support for Python 3.11 and 3.12 has been dropped to standardize the runtime and
remove older-Python dependency resolutions. Recreate environments with Python
3.13 before running `uv sync --locked`.

## Compatibility changes

[PyArrow 26](https://arrow.apache.org/blog/2026/10/08/26.0.0-release/) drops
Python 3.10 and requires NumPy 2.x and pandas 2.2.2+ for their optional
integrations. The example's development dependencies now require pandas 3 and pytest 9,
matching their current major versions. The Arrow-only native v2 runtime still needs only PyArrow and the
ADBC driver manager. The oldest-dependency CI lane now uses PyArrow 26.0.0,
while retaining the existing dbt Core, dbt adapter, and ADBC manager floors.

[Polars 2](https://docs.pola.rs/releases/upgrade/2/) changes lazy collection to
use the streaming engine by default. The adapter retains normal Polars
collection behavior and converts the result with `to_arrow()`. Its existing
functional Python-model tests exercise lazy Polars results, pandas results,
Arrow tables/readers, empty results, and table replacement. Native v2 parity
also exercises Arrow Python models and the CSV loader against the pinned
engine and driver.

## Remaining upstream constraints

These versions were rechecked against PyPI release metadata on October 22,
2026. The lockfile selects the newest releases allowed by the current dbt
packages and supported Python versions. Do not override upstream requirements
to force these upgrades; recheck when dbt publishes compatible releases.
Explicit resolver checks of the latest DeepDiff, more-itertools, protobuf, and
python-dateutil majors against dbt-core 1.12.6 and dbt-adapters 1.24.5 each
returned an unsatisfiable dependency conflict. All direct dependencies resolve
to their latest stable releases on Python 3.13.

| Library | Locked version | Latest stable | Reason retained |
| --- | --- | --- | --- |
| agate | 1.9.1 | 1.14.2 | dbt-common 1.39.0 requires `<1.10` |
| DeepDiff | 8.6.2 | 9.1.0 | dbt-common 1.39.0 requires `<9.0` |
| mashumaro | 3.17 | 3.23 | dbt-core 1.12.6 and dbt-adapters 1.24.5 require `<3.18` |
| more-itertools | 10.8.0 | 11.2.1 | metricflow 0.213.0 requires `<11.0` |
| pathspec | 1.0.4 | 1.1.1 | dbt-core 1.12.6 and dbt-common 1.39.0 require `<1.1` |
| protobuf | 6.33.6 | 7.36.2 | dbt-adapters 1.24.5 and dbt-common 1.39.0 require `<7.0` |
| python-dateutil | 2.9.0.post0 | 3.0.0 | dbt-common requires `<3.0`; metricflow requires `<2.10` |

Sources: [dbt-common metadata](https://pypi.org/pypi/dbt-common/1.39.0/json),
[dbt-core metadata](https://pypi.org/pypi/dbt-core/1.12.6/json),
[dbt-adapters metadata](https://pypi.org/pypi/dbt-adapters/1.24.5/json),
and [MetricFlow metadata](https://pypi.org/pypi/metricflow/0.213.0/json).

NetworkX 3.7 and NumPy 2.5.4 now resolve uniformly to their latest stable
versions; older-Python fallback versions are no longer needed.

ADBC driver manager 1.12.0, hatchling 1.32.4, and dbt_utils 1.4.1 were already
current. CI audits the locked runtime and development dependencies and the
optional native v2 requirements. The Redis driver and native dbt engine remain
pinned to the implementation recorded in `v2/upstream.json`; their source
changes belong in their respective repositories.
