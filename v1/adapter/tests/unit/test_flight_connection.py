"""Transport regressions, without a Redis or Flight server."""

from unittest.mock import MagicMock, patch

import pytest
from dbt.adapters.contracts.connection import Connection, ConnectionState
from dbt_common.exceptions import DbtRuntimeError

from dbt.adapters.redis_adbc.connections import RedisAdbcCredentials, RedisAdbcConnectionManager


def credentials(**kwargs):
    return RedisAdbcCredentials(database="redis", schema='a"b', **kwargs)


def test_native_options_remain_native():
    assert credentials(time_zone="UTC", rename_rekey=False).db_kwargs() == {
        "uri": "redis://localhost:6379/0", "adbc.redis.default_schema": 'a"b',
        "adbc.redis.rename_rekey": "false", "adbc.redis.time_zone": "UTC",
    }


def test_flight_options_do_not_include_backend_settings():
    opts = credentials(transport="flightsql", uri="grpc+tls://example:8815",
                       time_zone="UTC", username="alice", password="secret").db_kwargs()
    assert opts == {"uri": "grpc+tls://example:8815", "username": "alice", "password": "secret",
                    "adbc.flight.sql.rpc.with_cookie_middleware": "true"}


@pytest.mark.parametrize("kwargs", [
    {"rename_rekey": False}, {"aggregate_pushdown": "all"},
    {"read_timeout": 0}, {"write_timeout": "30s"},
    {"driver_options": {"adbc.redis.cluster": True}},
    {"driver_options": {"adbc.flight.sql.rpc.with_cookie_middleware": False}},
    {"uri": "redis://localhost:6379"},
])
def test_incompatible_flight_options_fail_early(kwargs):
    with pytest.raises(DbtRuntimeError):
        credentials(transport="flightsql", **{"uri": "grpc://localhost:8815", **kwargs}).db_kwargs()


def test_flight_driver_discovery_ignores_native_environment(monkeypatch):
    monkeypatch.setenv("REDIS_ADBC_DRIVER", "/wrong/native/driver")
    flight = MagicMock()
    flight._driver_path.return_value = "/flight/library.so"
    with patch.dict("sys.modules", adbc_driver_flightsql=flight):
        assert credentials(transport="flightsql").driver_path() == "/flight/library.so"


def test_flight_session_setup_and_escaping():
    creds = credentials(transport="flightsql", uri="grpc://localhost:8815", driver="/flight.so",
                        time_zone="a'b")
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    connection = Connection(type="redis_adbc", name="test", state=ConnectionState.INIT,
                            transaction_open=False, credentials=creds)
    with patch("dbt.adapters.redis_adbc.connections.dbapi.connect", return_value=conn):
        RedisAdbcConnectionManager.open(connection)
    assert connection.state == ConnectionState.OPEN
    assert [call.args[0] for call in cursor.execute.call_args_list] == [
        "SELECT 1", 'SET search_path TO "a""b"', "SET TIME ZONE 'a''b'",
    ]


def test_failed_session_initialization_closes_connection():
    creds = credentials(transport="flightsql", uri="grpc://localhost:8815", driver="/flight.so")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError("session setup failed")
    connection = Connection(type="redis_adbc", name="test", state=ConnectionState.INIT,
                            transaction_open=False, credentials=creds)
    with patch("dbt.adapters.redis_adbc.connections.dbapi.connect", return_value=conn):
        with pytest.raises(Exception, match="session setup failed"):
            RedisAdbcConnectionManager.open(connection)
    conn.close.assert_called_once()


def test_driver_option_secrets_are_redacted():
    info = dict(credentials(transport="flightsql", driver_options={
        "adbc.flight.sql.authorization_header": "secret-token",
    }).connection_info())
    assert "secret-token" not in str(info)


def test_rbac_grants_are_explicit_and_native():
    from types import SimpleNamespace
    from dbt.adapters.redis_adbc.impl import RedisAdbcAdapter

    for transport, options, expected in [
        ("redis", None, False),
        ("redis", {"adbc.redis.rbac": ""}, False),
        ("redis", {"adbc.redis.rbac": '{"password":"secret"}'}, True),
        ("flightsql", {"adbc.redis.rbac": "configured"}, False),
    ]:
        adapter = SimpleNamespace(config=SimpleNamespace(credentials=SimpleNamespace(
            transport=transport, driver_options=options,
        )))
        assert RedisAdbcAdapter.rbac_grants_enabled(adapter) is expected

    creds = credentials(driver_options={"adbc.redis.rbac": '{"password":"secret"}'})
    assert dict(creds.connection_info())["driver_options"] == {"adbc.redis.rbac": "<redacted>"}
