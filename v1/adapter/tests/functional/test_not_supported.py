"""The suite's tests for what Redis doesn't have, skipped with the reason."""

import pytest

from dbt.tests.adapter.grants.test_incremental_grants import BaseIncrementalGrants
from dbt.tests.adapter.grants.test_invalid_grants import BaseInvalidGrants
from dbt.tests.adapter.grants.test_model_grants import BaseModelGrants
from dbt.tests.adapter.grants.test_seed_grants import BaseSeedGrants
from dbt.tests.adapter.grants.test_snapshot_grants import BaseSnapshotGrants

NO_GRANTS = pytest.mark.skip(reason="General grants suite requires unsupported privileges/objects; opt-in native SELECT RBAC has a separate integration test")


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
