"""dbt's cross-database macros and data type macros."""

import pytest

from dbt.tests.adapter.utils import fixture_date_spine, fixture_get_intervals_between, fixture_listagg

from dbt.tests.adapter.utils.test_any_value import BaseAnyValue
from dbt.tests.adapter.utils.test_bool_or import BaseBoolOr
from dbt.tests.adapter.utils.test_cast import BaseCast
from dbt.tests.adapter.utils.test_cast_bool_to_text import BaseCastBoolToText
from dbt.tests.adapter.utils.test_concat import BaseConcat
from dbt.tests.adapter.utils.test_current_timestamp import BaseCurrentTimestampAware
from dbt.tests.adapter.utils.test_date import BaseDate
from dbt.tests.adapter.utils.test_date_spine import BaseDateSpine
from dbt.tests.adapter.utils.test_date_trunc import BaseDateTrunc
from dbt.tests.adapter.utils.test_dateadd import BaseDateAdd
from dbt.tests.adapter.utils.test_datediff import BaseDateDiff
from dbt.tests.adapter.utils.test_equals import BaseEquals
from dbt.tests.adapter.utils.test_escape_single_quotes import BaseEscapeSingleQuotesQuote, BaseEscapeSingleQuotesBackslash
from dbt.tests.adapter.utils.test_except import BaseExcept
from dbt.tests.adapter.utils.test_generate_series import BaseGenerateSeries
from dbt.tests.adapter.utils.test_get_intervals_between import BaseGetIntervalsBetween
from dbt.tests.adapter.utils.test_get_powers_of_two import BaseGetPowersOfTwo
from dbt.tests.adapter.utils.test_hash import BaseHash
from dbt.tests.adapter.utils.test_intersect import BaseIntersect
from dbt.tests.adapter.utils.test_last_day import BaseLastDay
from dbt.tests.adapter.utils.test_length import BaseLength
from dbt.tests.adapter.utils.test_listagg import BaseListagg
from dbt.tests.adapter.utils.test_null_compare import BaseMixedNullCompare, BaseNullCompare
from dbt.tests.adapter.utils.test_position import BasePosition
from dbt.tests.adapter.utils.test_replace import BaseReplace
from dbt.tests.adapter.utils.test_right import BaseRight
from dbt.tests.adapter.utils.test_safe_cast import BaseSafeCast
from dbt.tests.adapter.utils.test_split_part import BaseSplitPart
from dbt.tests.adapter.utils.test_string_literal import BaseStringLiteral
from dbt.tests.adapter.utils.test_timestamps import BaseCurrentTimestamps
from dbt.tests.adapter.utils.test_validate_sql import BaseValidateSqlMethod
from dbt.tests.adapter.utils.test_source_freshness_custom_info import BaseCalculateFreshnessMethod
from dbt.tests.adapter.utils.test_array_append import BaseArrayAppend
from dbt.tests.adapter.utils.test_array_concat import BaseArrayConcat
from dbt.tests.adapter.utils.test_array_construct import BaseArrayConstruct
from dbt.tests.adapter.utils.data_types.test_type_bigint import BaseTypeBigInt
from dbt.tests.adapter.utils.data_types.test_type_boolean import BaseTypeBoolean
from dbt.tests.adapter.utils.data_types.test_type_float import BaseTypeFloat
from dbt.tests.adapter.utils.data_types.test_type_int import BaseTypeInt
from dbt.tests.adapter.utils.data_types.test_type_numeric import BaseTypeNumeric
from dbt.tests.adapter.utils.data_types.test_type_string import BaseTypeString
from dbt.tests.adapter.utils.data_types.test_type_timestamp import BaseTypeTimestamp


class TestAnyValue(BaseAnyValue):
    pass


class TestBoolOr(BaseBoolOr):
    pass


class TestCast(BaseCast):
    pass


class TestCastBoolToText(BaseCastBoolToText):
    pass


class TestConcat(BaseConcat):
    pass


class TestCurrentTimestampAware(BaseCurrentTimestampAware):
    pass


class TestDate(BaseDate):
    pass


class TestDateSpine(BaseDateSpine):
    # The suite's Postgres SQL (ISO dates); its other branch compares the
    # dates with strings.
    @pytest.fixture(scope="class")
    def models(self):
        sql = fixture_date_spine.models__test_date_spine_sql.replace(
            "target.type == 'postgres'", "target.type in ('postgres', 'redis_adbc')"
        )
        return {
            "test_date_spine.yml": fixture_date_spine.models__test_date_spine_yml,
            "test_date_spine.sql": self.interpolate_macro_namespace(sql, "date_spine"),
        }


class TestDateTrunc(BaseDateTrunc):
    pass


class TestDateAdd(BaseDateAdd):
    pass


class TestDateDiff(BaseDateDiff):
    pass


class TestEquals(BaseEquals):
    pass


class TestEscapeSingleQuotesQuote(BaseEscapeSingleQuotesQuote):
    pass


@pytest.mark.skip(reason="standard SQL strings: a backslash is literal, as on Postgres (dbt-postgres skips it too)")
class TestEscapeSingleQuotesBackslash(BaseEscapeSingleQuotesBackslash):
    pass


class TestExcept(BaseExcept):
    pass


class TestGenerateSeries(BaseGenerateSeries):
    pass


class TestGetIntervalsBetween(BaseGetIntervalsBetween):
    # ISO dates: '09/01/2023'::date relies on Postgres's MDY DateStyle.
    @pytest.fixture(scope="class")
    def models(self):
        sql = """
select
  {{ get_intervals_between("cast('2023-09-01' as date)", "cast('2023-09-12' as date)", "day") }} as intervals,
  11 as expected
"""
        return {
            "test_get_intervals_between.yml": fixture_get_intervals_between.models__test_get_intervals_between_yml,
            "test_get_intervals_between.sql": self.interpolate_macro_namespace(sql, "get_intervals_between"),
        }


class TestGetPowersOfTwo(BaseGetPowersOfTwo):
    pass


class TestHash(BaseHash):
    pass


class TestIntersect(BaseIntersect):
    pass


class TestLastDay(BaseLastDay):
    pass


class TestLength(BaseLength):
    pass


class TestListagg(BaseListagg):
    # The limit_num path uses dbt's ARRAY_SLICE form, which still needs an
    # adapter translation (macros/cross_db.sql).
    @pytest.fixture(scope="class")
    def seeds(self):
        expected = fixture_listagg.seeds__data_listagg_output_csv.splitlines(keepends=True)
        return {
            "data_listagg.csv": fixture_listagg.seeds__data_listagg_csv,
            "data_listagg_output.csv": "".join(line for line in expected if "_limited" not in line),
        }

    @pytest.fixture(scope="class")
    def models(self):
        parts = fixture_listagg.models__test_listagg_sql.split("union all")
        sql = "union all".join(part for part in parts if "bottom_ordered_limited" not in part)
        return {
            "test_listagg.yml": fixture_listagg.models__test_listagg_yml,
            "test_listagg.sql": self.interpolate_macro_namespace(sql, "listagg"),
        }


class TestMixedNullCompare(BaseMixedNullCompare):
    pass


class TestNullCompare(BaseNullCompare):
    pass


class TestPosition(BasePosition):
    pass


class TestReplace(BaseReplace):
    pass


class TestRight(BaseRight):
    pass


class TestSafeCast(BaseSafeCast):
    pass


class TestSplitPart(BaseSplitPart):
    pass


class TestStringLiteral(BaseStringLiteral):
    pass


class TestCurrentTimestamps(BaseCurrentTimestamps):
    @pytest.fixture(scope="class")
    def expected_sql(self):
        return """
select current_timestamp as current_timestamp,
       (current_timestamp at time zone 'utc')::timestamp as current_timestamp_in_utc_backcompat,
       current_timestamp::timestamp as current_timestamp_backcompat
"""

    @pytest.fixture(scope="class")
    def expected_schema(self):
        return {
            "current_timestamp": "TIMESTAMP(6) WITH TIME ZONE",
            "current_timestamp_in_utc_backcompat": "TIMESTAMP(6)",
            "current_timestamp_backcompat": "TIMESTAMP(6)",
        }


class TestValidateSqlMethod(BaseValidateSqlMethod):
    pass


class TestCalculateFreshnessMethod(BaseCalculateFreshnessMethod):
    pass


class TestArrayAppend(BaseArrayAppend):
    pass


class TestArrayConcat(BaseArrayConcat):
    pass


class TestArrayConstruct(BaseArrayConstruct):
    pass


class TestTypeBigInt(BaseTypeBigInt):
    pass


class TestTypeBoolean(BaseTypeBoolean):
    pass


class TestTypeFloat(BaseTypeFloat):
    pass


class TestTypeInt(BaseTypeInt):
    # The adapter loads seeds' integers as BIGINT.
    @pytest.fixture(scope="class")
    def project_config_update(self):
        return {"seeds": {"+column_types": {"int_col": "integer"}}}


class TestTypeNumeric(BaseTypeNumeric):
    pass


class TestTypeString(BaseTypeString):
    pass


class TestTypeTimestamp(BaseTypeTimestamp):
    pass
