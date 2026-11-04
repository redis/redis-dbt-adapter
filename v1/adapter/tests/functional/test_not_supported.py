"""The suite's tests for what Redis doesn't have, skipped with the reason."""

import pytest

from dbt.tests.adapter.grants.test_incremental_grants import BaseIncrementalGrants
from dbt.tests.adapter.grants.test_invalid_grants import BaseInvalidGrants
from dbt.tests.adapter.grants.test_model_grants import BaseModelGrants
from dbt.tests.adapter.grants.test_seed_grants import BaseSeedGrants
from dbt.tests.adapter.grants.test_snapshot_grants import BaseSnapshotGrants
from dbt.tests.adapter.materialized_view.basic import MaterializedViewBasic
from dbt.tests.adapter.materialized_view.changes import MaterializedViewChanges

NO_GRANTS = pytest.mark.skip(reason="General grants suite requires unsupported privileges/objects; opt-in native SELECT RBAC has a separate integration test")
NO_MATERIALIZED_VIEWS = pytest.mark.skip(reason="Redis has no materialized views")


@NO_GRANTS
class TestModelGrants(BaseModelGrants):
    pass


@NO_GRANTS
class TestIncrementalGrants(BaseIncrementalGrants):
    pass


@NO_GRANTS
class TestSeedGrants(BaseSeedGrants):
    pass


@NO_GRANTS
class TestSnapshotGrants(BaseSnapshotGrants):
    pass


@NO_GRANTS
class TestInvalidGrants(BaseInvalidGrants):
    pass


@NO_MATERIALIZED_VIEWS
class TestMaterializedViewBasic(MaterializedViewBasic):
    pass


@NO_MATERIALIZED_VIEWS
class TestMaterializedViewChanges(MaterializedViewChanges):
    pass

