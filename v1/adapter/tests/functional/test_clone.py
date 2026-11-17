from dbt.tests.adapter.dbt_clone.test_dbt_clone import (
    BaseClonePossible,
    BaseCloneNotPossible,
    BaseCloneSameTargetAndState,
)


# The native zero-copy positive suite does not describe Redis's view fallback.
# Its capability-independent missing-state regression still runs normally.
class TestCloneNoState(BaseClonePossible):
    test_can_clone_true = None

    def test_zero_copy_capability_is_false(self, project):
        from dbt.tests.util import get_connection
        with get_connection(project.adapter):
            assert project.adapter.execute_macro('can_clone_table') is False


class TestCloneNotPossible(BaseCloneNotPossible):
    pass


class TestCloneSameSourceAndTarget(BaseCloneNotPossible):
    test_can_clone_false = None

    def test_clone_same_source_and_target(self, project, unique_schema):
        from dbt.tests.util import run_dbt, run_dbt_and_capture
        self.run_and_save_state(project.project_root)
        before = project.run_sql(f"select * from {unique_schema}.table_model", fetch="all")
        results, _ = run_dbt_and_capture(["clone", "--state", "state", "--full-refresh"])
        assert all(result.status == "success" for result in results)
        assert project.run_sql(f"select * from {unique_schema}.table_model", fetch="all") == before
        # Existing same-name objects must stay readable and must not become self-referencing views.
        results = run_dbt(["test"])
        assert all(result.status == "pass" for result in results)


class TestCloneSameTargetAndState(BaseCloneSameTargetAndState):
    pass
