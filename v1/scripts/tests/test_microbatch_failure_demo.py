"""Check the fault boundary and recovery oracle without Redis."""

from pathlib import Path
from contextlib import redirect_stdout
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from microbatch_failure_demo import delete_prefix, run_demo, verify_rows


class FailureDemoTests(unittest.TestCase):
    target = '"demo"."fct_trips_microbatch"'

    def test_missing_enterprise_config_fails_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "REDIS_URI"):
                run_demo("taxi_intermediate")

    def test_only_delete_is_sent_at_the_fault_boundary(self):
        delete = f"/* dbt query comment */\ndelete from {self.target} as DBT_INTERNAL_TARGET\nwhere pickup_datetime >= '2019-01-02' and pickup_datetime < '2019-01-03'"
        sql = delete + f';\n insert into {self.target} ("trip_id") (select "trip_id" from "temp")'
        self.assertEqual(delete_prefix(sql, self.target), delete)
        self.assertIsNone(delete_prefix(sql, '"other"."fct_trips_microbatch"'))
        self.assertIsNone(delete_prefix(f'insert into {self.target} ("trip_id") values (1)', self.target))
        self.assertIsNone(delete_prefix(delete, self.target))

    def test_default_unquoted_relation_sql(self):
        target = "dbt_microbatch_failure_123.fct_trips_microbatch"
        delete = f"delete from {target} as DBT_INTERNAL_TARGET where pickup_datetime < '2019-01-03'"
        self.assertEqual(delete_prefix(delete + f'; insert into {target} ("trip_id") (select 1)', target), delete)

    def test_recovery_checks_values_and_neighboring_days_not_only_counts(self):
        expected = [(1, "2019-01-01"), (2, "2019-01-02"), (3, "2019-01-03")]
        for bad in [expected[:-1], [expected[0], expected[1], (3, "changed")],
                    [expected[0], expected[1], expected[1]]]:
            with self.subTest(rows=bad), self.assertRaises(RuntimeError):
                verify_rows(bad, expected, "recovery")

    def test_duplicate_source_ids_are_rejected_even_when_rows_match(self):
        rows = [(1, "first"), (1, "second")]
        with self.assertRaisesRegex(RuntimeError, "duplicate trip_id"):
            verify_rows(rows, rows, "baseline")

    def test_complete_recovery_accepts_rows_in_a_different_order(self):
        rows = [(1, "2019-01-01 12:00:00", "2019-01-01"),
                (2, "2019-01-02 12:00:00", "2019-01-02")]
        with redirect_stdout(io.StringIO()) as output:
            verify_rows(list(reversed(rows)), rows, "recovery")
        self.assertIn("2 rows, no duplicate trip_id", output.getvalue())


if __name__ == "__main__":
    unittest.main()
