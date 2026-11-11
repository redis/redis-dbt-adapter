"""Fixtures for dbt's adapter test suite (dbt-tests-adapter).

    uv run pytest -n 4

Each test class gets its own schema, which the suite drops afterwards. Point
REDIS_URI at a dedicated Redis Enterprise test cluster using rediss://.
REDIS_USERNAME and REDIS_PASSWORD are required. REDIS_ADBC_DRIVER works
as for the project.
"""

import os
import sys
from pathlib import Path

import pytest

from dbt.tests.util import get_connection

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
from integration_config import require_integration_config

pytest_plugins = ["dbt.tests.fixtures.project"]

# `make driver` puts it here. The suite runs each test from a temporary
# directory, so the path must be absolute.
DRIVER = Path(__file__).resolve().parents[3] / "driver" / "libadbc_driver_redis"

@pytest.fixture(scope="class")
def dbt_profile_target():
    require_integration_config()
    transport = os.environ.get("REDIS_ADBC_TRANSPORT", "redis")
    if transport == "flightsql":
        # REDIS_* describes the dedicated TLS Enterprise backend; Flight
        # endpoint credentials and trust belong to the separate client hop.
        options = {}
        if os.environ.get("FLIGHT_SQL_TLS_CA_FILE"):
            options["adbc.flight.sql.client_option.tls_root_certs"] = Path(
                os.environ["FLIGHT_SQL_TLS_CA_FILE"]
            ).read_text()
        uri = os.environ["FLIGHT_SQL_URI"]
        username = os.environ.get("FLIGHT_SQL_USERNAME", "")
        password = os.environ.get("FLIGHT_SQL_PASSWORD", "")
    else:
        options = {"adbc.redis.tls_ca_file": os.environ["REDIS_TLS_CA_FILE"]} \
            if os.environ.get("REDIS_TLS_CA_FILE") else {}
        uri = os.environ["REDIS_URI"]
        username = os.environ["REDIS_USERNAME"]
        password = os.environ["REDIS_PASSWORD"]
    target = {
        "type": "redis_adbc",
        "transport": transport,
        "uri": uri,
        "username": username,
        "password": password,
        "driver_options": options,
        "threads": 4,
    }
    if os.environ.get("REDIS_ADBC_DRIVER") or transport == "redis":
        target["driver"] = os.environ.get("REDIS_ADBC_DRIVER") or str(DRIVER)
    return target


@pytest.fixture(scope="class")
def profile_user():
    # The suite's default reads the Postgres profile's `user`; the docs
    # catalog has no owner here.
    return None


@pytest.fixture(scope="class", autouse=True)
def drop_extra_schemas(project):
    """Drop the schemas dbt made for a test besides its own (…_seeds,
    …_dbt_test__audit, …): the suite drops only the ones it created, and
    the rest would stay in Redis. The suite's teardown, which runs after
    this, drops them."""
    yield
    with get_connection(project.adapter):
        schemas = project.adapter.list_schemas(project.database)
    project.created_schemas.extend(
        s for s in schemas if s.startswith(project.test_schema) and s not in project.created_schemas
    )
