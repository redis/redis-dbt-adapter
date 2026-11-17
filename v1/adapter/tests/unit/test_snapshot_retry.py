"""Retry refused publications without replaying committed SQL or consumed input."""

from unittest.mock import MagicMock, patch

import adbc_driver_manager as adbc
import pyarrow as pa
import pytest

from dbt.adapters.redis_adbc.connections import RedisAdbcCursor, RedisAdbcHandle


def conflict(message="snapshot catalog changed concurrently; retry the statement", state="40001"):
    return adbc.OperationalError(message, status_code=adbc.AdbcStatusCode.IO, sqlstate=state)


def cursor_with_errors(errors):
    cursors = [MagicMock(rowcount=1) for _ in errors]
    for cursor, error in zip(cursors, errors):
        cursor.execute.side_effect = error
        cursor.adbc_ingest.side_effect = error
    conn = MagicMock()
    conn.cursor.side_effect = cursors
    return RedisAdbcCursor(conn), cursors


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_refused_statement_retries_with_a_new_cursor(sleep):
    cursor, cursors = cursor_with_errors([conflict(), conflict(), None])
    sql = "/* dbt */ insert into t values ('a;b');"
    assert cursor.execute(sql) is cursor
    for raw in cursors:
        raw.execute.assert_called_once_with(sql)
    for raw in cursors[:-1]:
        raw.close.assert_called_once()
    assert cursor.rowcount == 1
    assert sleep.call_count == 2


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_script_does_not_replay_committed_prefix(sleep):
    cursor, cursors = cursor_with_errors([None, None])
    cursors[0].execute.side_effect = [None, conflict()]
    cursor.execute("insert into t values (1); insert into t values (2);")
    assert [call.args[0] for call in cursors[0].execute.call_args_list] == [
        "insert into t values (1);", "insert into t values (2);",
    ]
    cursors[1].execute.assert_called_once_with("insert into t values (2);")


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_retries_are_bounded_and_preserve_error(sleep):
    errors = [conflict() for _ in range(20)]
    cursor, cursors = cursor_with_errors(errors)
    with pytest.raises(adbc.OperationalError) as raised:
        cursor.execute("create table t (id int)")
    assert raised.value is errors[-1]
    assert sleep.call_count == 19
    assert all(raw.execute.call_count == 1 for raw in cursors)


@pytest.mark.parametrize("parameters,error", [
    ((1,), conflict()),
    (None, conflict(state="08006")),
    (None, conflict("publication outcome unknown")),
    (None, conflict("snapshot retention expired")),
    (None, adbc.OperationalError("cancelled", status_code=adbc.AdbcStatusCode.CANCELLED)),
    (None, adbc.OperationalError(
        "snapshot catalog changed concurrently; retry the statement",
        status_code=adbc.AdbcStatusCode.CANCELLED, sqlstate="40001")),
])
@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_unsafe_replays_are_refused(sleep, parameters, error):
    cursor, cursors = cursor_with_errors([error])
    with pytest.raises(adbc.OperationalError) as raised:
        cursor.execute("insert into t values (?)", parameters)
    assert raised.value is error
    cursors[0].execute.assert_called_once()
    sleep.assert_not_called()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_arrow_table_supplies_reusable_input(sleep):
    cursor, cursors = cursor_with_errors([conflict(), None])
    table = pa.table({"id": [1, 2]})
    cursor.adbc_ingest("t", table, mode="append")
    for raw in cursors:
        raw.adbc_ingest.assert_called_once_with("t", table, mode="append")
    sleep.assert_called_once()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_arrow_reader_is_captured_once_and_reopened_for_retry(sleep):
    cursor, cursors = cursor_with_errors([conflict(), None])
    table = pa.table({"id": [1, 2, 3]})
    seen = []

    def ingest(name, reader):
        seen.append(reader.read_all().to_pylist())
        if len(seen) == 1:
            raise conflict()
        return 3

    for raw in cursors:
        raw.adbc_ingest.side_effect = ingest
    assert cursor.adbc_ingest("t", table.to_reader(max_chunksize=1)) == 3
    assert seen == [table.to_pylist(), table.to_pylist()]
    sleep.assert_called_once()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_unknown_stream_is_never_replayed(sleep):
    cursor, cursors = cursor_with_errors([conflict()])
    with pytest.raises(adbc.OperationalError):
        cursor.adbc_ingest("t", object())
    cursors[0].adbc_ingest.assert_called_once()
    sleep.assert_not_called()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_fetch_failure_is_never_replayed(sleep):
    cursor, cursors = cursor_with_errors([None])
    cursors[0].fetchall.side_effect = conflict()
    cursor.execute("select * from t")
    with pytest.raises(adbc.OperationalError):
        cursor.fetchall()
    cursors[0].execute.assert_called_once()
    sleep.assert_not_called()


def test_context_manager_and_handle_close_latest_cursor():
    conn = MagicMock()
    handle = RedisAdbcHandle(conn)
    with handle.cursor() as cursor:
        assert isinstance(cursor, RedisAdbcCursor)
    conn.cursor.return_value.close.assert_called_once()
    handle.close()
    conn.close.assert_called_once()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_flight_handle_retries_explicit_wire_refusal(sleep):
    first, second = MagicMock(), MagicMock()
    first.execute.side_effect = adbc.OperationalError(
        "[redis] snapshot catalog changed concurrently; retry the statement (40001) (Unavailable; ExecuteUpdate)",
        status_code=adbc.AdbcStatusCode.IO, vendor_code=14,
    )
    conn = MagicMock()
    conn.cursor.side_effect = [first, second]
    RedisAdbcHandle(conn, native=False).cursor().execute("insert into t values (1)")
    first.execute.assert_called_once_with("insert into t values (1)")
    second.execute.assert_called_once_with("insert into t values (1)")
    sleep.assert_called_once()


@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_flight_refused_publication_preserves_statement_boundary(sleep):
    error = adbc.OperationalError(
        "[FlightSQL] I/O: [redis] snapshot catalog changed concurrently; retry the statement (40001) (Unavailable; ExecuteUpdate)",
        status_code=adbc.AdbcStatusCode.IO, vendor_code=14,
    )
    cursor, cursors = cursor_with_errors([None, None])
    cursor._native = False
    cursors[0].execute.side_effect = [None, error]
    cursor.execute("insert into t values (1); insert into t values (2);")
    assert [call.args[0] for call in cursors[0].execute.call_args_list] == [
        "insert into t values (1);", "insert into t values (2);",
    ]
    cursors[1].execute.assert_called_once_with("insert into t values (2);")
    sleep.assert_called_once()


@pytest.mark.parametrize("message,status,vendor", [
    ("snapshot catalog changed concurrently; retry the statement", adbc.AdbcStatusCode.IO, 14),
    ("[redis] snapshot catalog changed concurrently; retry the statement (40001) (Unavailable; ExecuteUpdate)", adbc.AdbcStatusCode.IO, 8),
    ("[redis] snapshot catalog changed concurrently; retry the statement (40001) (Unavailable; ExecuteUpdate)", adbc.AdbcStatusCode.CANCELLED, 14),
    ("publication outcome unknown (Unavailable; ExecuteUpdate)", adbc.AdbcStatusCode.IO, 14),
])
@patch("dbt.adapters.redis_adbc.connections.time.sleep")
def test_flight_does_not_retry_ambiguous_or_other_wire_errors(sleep, message, status, vendor):
    error = adbc.OperationalError(message, status_code=status, vendor_code=vendor, sqlstate="40001")
    cursor, cursors = cursor_with_errors([error])
    cursor._native = False
    with pytest.raises(adbc.Error) as raised:
        cursor.execute("insert into t values (1)")
    assert raised.value is error
    sleep.assert_not_called()
