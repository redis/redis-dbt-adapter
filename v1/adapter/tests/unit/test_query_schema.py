"""Flight schema discovery preserves SQL headers without opening a row stream."""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from dbt.adapters.redis_adbc.impl import RedisAdbcAdapter


def test_flight_schema_executes_headers_before_final_select():
    adapter = MagicMock()
    adapter.connections.exception_handler.side_effect = lambda _: nullcontext()
    cursor = adapter.connections.get_thread_connection.return_value.handle.cursor.return_value.__enter__.return_value
    expected = pa.schema([("id", pa.int64())])
    cursor.adbc_execute_schema.return_value = expected
    sql = "set time zone 'UTC'; select cast('a;b' as varchar) as id"

    assert RedisAdbcAdapter._flight_query_schema(adapter, sql) == expected
    cursor.execute.assert_called_once_with("set time zone 'UTC';")
    cursor.fetchall.assert_called_once()
    cursor.adbc_execute_schema.assert_called_once_with("select cast('a;b' as varchar) as id")
    assert cursor.execute.call_count == 1


def test_flight_schema_failure_still_closes_statement():
    adapter = MagicMock()
    adapter.connections.exception_handler.side_effect = lambda _: nullcontext()
    context = adapter.connections.get_thread_connection.return_value.handle.cursor.return_value
    context.__enter__.return_value.adbc_execute_schema.side_effect = RuntimeError("invalid query")
    with pytest.raises(RuntimeError, match="invalid query"):
        RedisAdbcAdapter._flight_query_schema(adapter, "select missing")
    context.__exit__.assert_called_once()
