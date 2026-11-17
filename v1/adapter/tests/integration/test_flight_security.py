"""Opt-in qualification of the Flight hop, independent of backend TLS checks."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

import adbc_driver_manager as adbc
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("FLIGHT_SQL_SECURITY_TESTS") != "1",
    reason="requires a dedicated authenticated TLS Flight SQL fixture",
)


class PrivateOptions(dict):
    def __repr__(self):
        return "<Flight SQL credentials and trust redacted>"


@pytest.fixture
def flight_config():
    uri = os.environ["FLIGHT_SQL_URI"]
    assert uri.startswith("grpc+tls://"), "qualification requires verified Flight TLS"
    return uri, PrivateOptions({
        "username": os.environ["FLIGHT_SQL_USERNAME"],
        "password": os.environ["FLIGHT_SQL_PASSWORD"],
        "adbc.flight.sql.client_option.tls_root_certs": Path(
            os.environ["FLIGHT_SQL_TLS_CA_FILE"]
        ).read_text(),
        "adbc.flight.sql.rpc.with_cookie_middleware": "true",
        "adbc.flight.sql.rpc.timeout_seconds.query": "15",
    })


def connect(uri, options):
    import adbc_driver_flightsql.dbapi

    return adbc_driver_flightsql.dbapi.connect(uri, db_kwargs=options, autocommit=True)


def query(connection, sql):
    from dbt.adapters.redis_adbc.connections import RedisAdbcCursor

    with RedisAdbcCursor(connection, native=False) as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def test_verified_tls_and_authentication(flight_config):
    uri, options = flight_config
    with connect(uri, options) as connection:
        assert query(connection, "select 42 as id") == [(42,)]


@pytest.mark.parametrize("credentials", [{}, {"username": "invalid", "password": "invalid"}])
def test_missing_and_incorrect_credentials_rejected(flight_config, credentials):
    uri, options = flight_config
    options = PrivateOptions({k: v for k, v in options.items() if k not in {"username", "password"}})
    options.update(credentials)
    with pytest.raises(adbc.Error, match="(?i)unauthenticated|authentication|credentials|authorization|WRONGPASS"):
        with connect(uri, options) as connection:
            query(connection, "select 1")


def test_untrusted_certificate_rejected(flight_config):
    uri, options = flight_config
    del options["adbc.flight.sql.client_option.tls_root_certs"]
    with pytest.raises(adbc.Error, match="(?i)certificate|tls|ssl"):
        with connect(uri, options) as connection:
            query(connection, "select 1")


def test_concurrent_sessions_recover_after_failed_statement(flight_config):
    uri, options = flight_config

    def worker(value):
        with connect(uri, options) as connection:
            # Acquire the cookie before creating a connection-local table.
            assert query(connection, "select 1") == [(1,)]
            try:
                query(connection, "create temp table dbt_flight_security_probe (id bigint)")
                query(connection, f"insert into dbt_flight_security_probe values ({value})")
                with pytest.raises(adbc.Error):
                    query(connection, "select * from dbt_flight_security_missing_table")
                assert query(connection, "select id from dbt_flight_security_probe") == [(value,)]
            finally:
                query(connection, "drop table if exists dbt_flight_security_probe")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
