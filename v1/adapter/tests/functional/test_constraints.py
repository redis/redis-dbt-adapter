import pytest

from dbt.tests.adapter.constraints import fixtures
from dbt.tests.adapter.constraints.test_constraints import (
    BaseConstraintQuotedColumn,
    BaseConstraintsRollback,
    BaseConstraintsRuntimeDdlEnforcement,
    BaseIncrementalConstraintsColumnsEqual,
    BaseIncrementalConstraintsRollback,
    BaseIncrementalConstraintsRuntimeDdlEnforcement,
    BaseIncrementalContractSqlHeader,
    BaseIncrementalForeignKeyConstraint,
    BaseModelConstraintsRuntimeEnforcement,
    BaseTableConstraintsColumnsEqual,
    BaseTableContractSqlHeader,
    BaseViewConstraintsColumnsEqual,
)


class RedisColumnTypes:
    @pytest.fixture
    def string_type(self):
        return "VARCHAR"

    @pytest.fixture
    def int_type(self):
        return "INTEGER"

    @pytest.fixture
    def data_types(self, schema_int_type, int_type, string_type):
        # sql_column_value, schema_data_type, error_data_type. These fixtures
        # exercise the scalar contract declarations below.
        return [
            ["1", schema_int_type, int_type],
            ["'1'", string_type, string_type],
            ["true", "boolean", "BOOLEAN"],
            ["cast('2013-11-03 00:00:00-07' as timestamp with time zone)", "timestamp with time zone", "TIMESTAMP WITH TIME ZONE"],
            ["cast('2013-11-03 00:00:00-07' as timestamp)", "timestamp", "TIMESTAMP"],
            ["cast('1' as numeric)", "numeric", "NUMERIC"],
        ]


# The suite's expected DDL, using the driver's INTEGER literals.
COLUMN_CONSTRAINTS_SQL = """
create table <model_identifier> (
    id integer not null primary key check ((id > 0)) check (id >= 1) references <foreign_key_model_identifier> (id) unique,
    color text,
    date_day text
) ;
insert into <model_identifier> (
    id ,
    color ,
    date_day
)
(
    select
       id,
       color,
       date_day
       from
    (
        -- depends_on: <foreign_key_model_identifier>
        select
            'blue' as color,
            1 as id,
            '2019-01-01' as date_day
    ) as model_subq
);
"""

MODEL_CONSTRAINTS_SQL = """
create table <model_identifier> (
    id integer not null,
    color text,
    date_day text,
    check ((id > 0)),
    check (id >= 1),
    primary key (id),
    constraint strange_uniqueness_requirement unique (color, date_day),
    foreign key (id) references <foreign_key_model_identifier> (id)
) ;
insert into <model_identifier> (
    id ,
    color ,
    date_day
)
(
    select
       id,
       color,
       date_day
       from
    (
        -- depends_on: <foreign_key_model_identifier>
        select
            'blue' as color,
            1 as id,
            '2019-01-01' as date_day
    ) as model_subq
);
"""

QUOTED_COLUMN_SQL = """
create table <model_identifier> (
    id integer not null,
    "from" text not null,
    date_day text,
    check (("from" = 'blue'))
) ;
insert into <model_identifier> (
    id, "from", date_day
)
(
    select id, "from", date_day
    from (
        select
          'blue' as "from",
          1 as id,
          '2019-01-01' as date_day
    ) as model_subq
);
"""


class TestTableConstraintsColumnsEqual(RedisColumnTypes, BaseTableConstraintsColumnsEqual):
    pass


class TestViewConstraintsColumnsEqual(RedisColumnTypes, BaseViewConstraintsColumnsEqual):
    pass


class TestIncrementalConstraintsColumnsEqual(RedisColumnTypes, BaseIncrementalConstraintsColumnsEqual):
    pass


class TestConstraintsRuntimeDdlEnforcement(BaseConstraintsRuntimeDdlEnforcement):
    @pytest.fixture(scope="class")
    def expected_sql(self):
        return COLUMN_CONSTRAINTS_SQL


class TestIncrementalConstraintsRuntimeDdlEnforcement(BaseIncrementalConstraintsRuntimeDdlEnforcement):
    @pytest.fixture(scope="class")
    def expected_sql(self):
        return COLUMN_CONSTRAINTS_SQL


class TestModelConstraintsRuntimeEnforcement(BaseModelConstraintsRuntimeEnforcement):
    @pytest.fixture(scope="class")
    def expected_sql(self):
        return MODEL_CONSTRAINTS_SQL


class TestConstraintQuotedColumn(BaseConstraintQuotedColumn):
    @pytest.fixture(scope="class")
    def expected_sql(self):
        return QUOTED_COLUMN_SQL


class TestConstraintsRollback(BaseConstraintsRollback):
    pass


class TestIncrementalConstraintsRollback(BaseIncrementalConstraintsRollback):
    pass


# Postgres's current_setting('timezone') isn't in the driver; the session time
# zone the header sets shows in current_timestamp's text instead.
SQL_HEADER_MODEL = """
{{{{ config(materialized="{materialized}", on_schema_change="append_new_columns") }}}}

{{% call set_sql_header(config) %}}
set session time zone 'Asia/Kolkata';
{{%- endcall %}}
select cast(current_timestamp as varchar) as column_name
"""


class TestTableContractSqlHeader(BaseTableContractSqlHeader):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model_contract_sql_header.sql": SQL_HEADER_MODEL.format(materialized="table"),
            "constraints_schema.yml": fixtures.model_contract_header_schema_yml,
        }


class TestIncrementalContractSqlHeader(BaseIncrementalContractSqlHeader):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model_contract_sql_header.sql": SQL_HEADER_MODEL.format(materialized="incremental"),
            "constraints_schema.yml": fixtures.model_contract_header_schema_yml,
        }


class TestIncrementalForeignKeyConstraint(BaseIncrementalForeignKeyConstraint):
    pass
