import pytest

from dbt.tests.adapter.basic.expected_catalog import base_expected_catalog, expected_references_catalog, no_stats
from dbt.tests.adapter.basic.test_adapter_methods import BaseAdapterMethod
from dbt.tests.adapter.basic.test_base import BaseSimpleMaterializations
from dbt.tests.adapter.basic.test_docs_generate import BaseDocsGenerate, BaseDocsGenReferences
from dbt.tests.adapter.basic.test_empty import BaseEmpty
from dbt.tests.adapter.basic.test_ephemeral import BaseEphemeral
from dbt.tests.adapter.basic.test_generic_tests import BaseGenericTests
from dbt.tests.adapter.basic.test_get_catalog_for_single_relation import BaseGetCatalogForSingleRelation
from dbt.tests.adapter.basic.test_incremental import (
    BaseIncremental,
    BaseIncrementalBadStrategy,
    BaseIncrementalNotSchemaChange,
)
from dbt.tests.adapter.basic.test_singular_tests import BaseSingularTests
from dbt.tests.adapter.basic.test_singular_tests_ephemeral import BaseSingularTestsEphemeral
from dbt.tests.adapter.basic.test_snapshot_check_cols import BaseSnapshotCheckCols
from dbt.tests.adapter.basic.test_snapshot_timestamp import BaseSnapshotTimestamp
from dbt.tests.adapter.basic.test_table_materialization import BaseTableMaterialization
from dbt.tests.adapter.basic.test_validate_connection import BaseValidateConnection


class TestSimpleMaterializations(BaseSimpleMaterializations):
    pass


class TestSingularTests(BaseSingularTests):
    pass


class TestSingularTestsEphemeral(BaseSingularTestsEphemeral):
    pass


class TestEmpty(BaseEmpty):
    pass


class TestEphemeral(BaseEphemeral):
    pass


class TestIncremental(BaseIncremental):
    pass


class TestIncrementalNotSchemaChange(BaseIncrementalNotSchemaChange):
    pass


class TestIncrementalBadStrategy(BaseIncrementalBadStrategy):
    pass


class TestGenericTests(BaseGenericTests):
    pass


class TestSnapshotCheckCols(BaseSnapshotCheckCols):
    pass


class TestSnapshotTimestamp(BaseSnapshotTimestamp):
    pass


class TestAdapterMethod(BaseAdapterMethod):
    pass


class TestValidateConnection(BaseValidateConnection):
    pass


class TestTableMaterialization(BaseTableMaterialization):
    pass


# The catalog's types are the driver's (GetObjects' xdbc_type_name): seeds'
# integers are BIGINT, and a TIMESTAMP has its precision. There's no owner and
# no table statistics.
CATALOG_TYPES = dict(
    role=None,
    id_type="BIGINT",
    text_type="VARCHAR",
    time_type="TIMESTAMP(6)",
    view_type="VIEW",
    table_type="BASE TABLE",
    model_stats=no_stats(),
)


class TestDocsGenerate(BaseDocsGenerate):
    @pytest.fixture(scope="class")
    def expected_catalog(self, project):
        return base_expected_catalog(project, **CATALOG_TYPES)


class TestDocsGenReferences(BaseDocsGenReferences):
    @pytest.fixture(scope="class")
    def expected_catalog(self, project):
        return expected_references_catalog(project, bigint_type="BIGINT", **CATALOG_TYPES)


class TestGetCatalogForSingleRelation(BaseGetCatalogForSingleRelation):
    def expected(self, project, name, kind):
        from dbt_common.contracts.metadata import CatalogTable, ColumnMetadata, StatsItem, TableMetadata
        types = {"id": "BIGINT", "first_name": "VARCHAR", "email": "VARCHAR",
                 "ip_address": "VARCHAR", "updated_at": "TIMESTAMP(6)"}
        return CatalogTable(
            metadata=TableMetadata(database=project.database, schema=project.test_schema, name=name, type=kind),
            columns={name: ColumnMetadata(name=name, index=i, type=dtype)
                     for i, (name, dtype) in enumerate(types.items(), 1)},
            stats={"has_stats": StatsItem(id="has_stats", label="Has Stats?", value=False,
                   description="Indicates whether there are statistics for this table", include=False)},
        )

    @pytest.fixture(scope="class")
    def expected_catalog_my_seed(self, project):
        return self.expected(project, "my_seed", "BASE TABLE")

    @pytest.fixture(scope="class")
    def expected_catalog_my_view_model(self, project):
        return self.expected(project, "my_view_model", "VIEW")

    def test_precise_metadata_and_missing_relation(self, project):
        from dbt.tests.util import get_connection
        schema = project.test_schema
        project.run_sql(f'create table {schema}."Quoted Table" ("Mixed Column" numeric(12,2), label varchar(42))')
        project.run_sql(f"comment on table {schema}.\"Quoted Table\" is 'Table description'")
        project.run_sql(f"comment on column {schema}.\"Quoted Table\".\"Mixed Column\" is 'Exact amount'")
        project.run_sql(f'create materialized view {schema}.catalog_mv as select * from {schema}."Quoted Table"')
        with get_connection(project.adapter):
            relation = project.adapter.Relation.create(database=project.database, schema=schema, identifier="Quoted Table")
            catalog = project.adapter.get_catalog_for_single_relation(relation)
            assert catalog.metadata.comment == 'Table description'
            assert list(catalog.columns) == ['Mixed Column', 'label']
            assert catalog.columns['Mixed Column'].type == 'NUMERIC(12,2)'
            assert catalog.columns['Mixed Column'].comment == 'Exact amount'
            assert catalog.columns['label'].type == 'VARCHAR(42)'
            mv = relation.incorporate(path={"identifier": "catalog_mv"})
            assert project.adapter.get_catalog_for_single_relation(mv).metadata.type == 'MATERIALIZED VIEW'
            assert project.adapter.get_catalog_for_single_relation(relation.incorporate(path={"identifier": "Quoted_Table"})) is None
            assert project.adapter.get_catalog_for_single_relation(relation.incorporate(path={"schema": schema + '_missing'})) is None
            assert project.adapter.get_catalog_for_single_relation(relation.incorporate(path={"database": 'other'})) is None
