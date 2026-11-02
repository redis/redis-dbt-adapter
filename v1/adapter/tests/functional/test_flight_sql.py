"""Live regressions for Redis-backed Flight SQL sessions and metadata."""

import os
from dataclasses import replace

import adbc_driver_manager
import pytest
from dbt.adapters.contracts.connection import Connection, ConnectionState
from dbt.tests.util import get_connection, run_dbt

from dbt.adapters.redis_adbc.connections import RedisAdbcConnectionManager


pytestmark = pytest.mark.skipif(
    os.environ.get("REDIS_ADBC_TRANSPORT") != "flightsql", reason="requires a Flight SQL server"
)


class TestFlightSessions:
    def test_temporary_tables_and_settings_are_connection_local(self, project):
        handles = []
        try:
            for zone in ("America/New_York", "UTC"):
                connection = Connection(
                    type="redis_adbc", name=zone, state=ConnectionState.INIT,
                    transaction_open=False,
                    credentials=replace(project.adapter.config.credentials, time_zone=zone),
                )
                handles.append(RedisAdbcConnectionManager.open(connection).handle)
            first, second = handles
            with first.cursor() as cursor:
                cursor.execute("CREATE TEMP TABLE flight_session_probe (id BIGINT)")
                cursor.execute("INSERT INTO flight_session_probe VALUES (7)")
            with first.cursor() as cursor:
                cursor.execute("SELECT id FROM flight_session_probe")
                assert cursor.fetchall() == [(7,)]
                cursor.execute("SHOW TimeZone")
                assert cursor.fetchall() == [("America/New_York",)]
            with second.cursor() as cursor:
                cursor.execute("SHOW TimeZone")
                assert cursor.fetchall() == [("UTC",)]
                with pytest.raises(adbc_driver_manager.Error):
                    cursor.execute("SELECT id FROM flight_session_probe")
        finally:
            if handles:
                with handles[0].cursor() as cursor:
                    cursor.execute("DROP TABLE IF EXISTS flight_session_probe")
            for handle in handles:
                handle.close()


class TestFlightColumnMetadata:
    @pytest.fixture(scope="class")
    def models(self):
        return {"column_types.sql": """
{{ config(materialized='table', persist_docs={'columns': true}) }}
select cast(12.34 as numeric(12,2)) as amount,
       cast('hello' as varchar(42)) as label,
       cast('2026-11-02 12:00:00' as timestamp(6)) as stamp
""", "schema.yml": """
version: 2
models:
  - name: column_types
    columns:
      - name: amount
        description: Exact decimal amount
"""}

    def test_sql_types_precision_and_comments(self, project):
        run_dbt(["run"])
        with get_connection(project.adapter):
            objects = project.adapter._get_objects("columns", schema=project.test_schema, table="column_types")
        columns = {
            c["column_name"]: c
            for cat in objects for s in cat["catalog_db_schemas"]
            for t in s["db_schema_tables"] for c in t["table_columns"]
        }
        assert columns["amount"]["xdbc_type_name"] == "NUMERIC(12,2)"
        assert columns["label"]["xdbc_type_name"] == "VARCHAR(42)"
        assert columns["stamp"]["xdbc_type_name"] == "TIMESTAMP(6)"
        assert columns["amount"]["remarks"] == "Exact decimal amount"
