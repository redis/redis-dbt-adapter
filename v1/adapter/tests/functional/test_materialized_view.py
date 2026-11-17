"""Native ADBC materialized-view lifecycle, metadata, catalog and indexes."""
import json
from pathlib import Path

import pytest
from dbt.adapters.contracts.relation import RelationType
from dbt.tests.util import get_connection, run_dbt, run_dbt_and_capture, write_file

MODEL = """{{ config(materialized='materialized_view', INDEX_CONFIG) }}
select id, value from {{ ref('source_rows') }}
"""


class TestMaterializedView:
    @pytest.fixture(scope="class")
    def seeds(self):
        return {"source_rows.csv": "id,value\n1,100\n2,200\n"}

    @pytest.fixture(scope="class")
    def models(self):
        return {
            "totals.sql": MODEL.replace("INDEX_CONFIG", "indexes=[{'columns': ['id']}]"),
            "schema.yml": """version: 2
models:
  - name: totals
    description: Stored totals
    config:
      persist_docs: {relation: true, columns: true}
    columns:
      - name: id
        description: Row identifier
        data_tests: [not_null, unique]
""",
        }

    def relation(self, project):
        with get_connection(project.adapter):
            return project.adapter.get_relation(project.database, project.test_schema, "totals")

    def indexes(self, project):
        return project.run_sql(
            f"select indexname from pg_indexes where schemaname = '{project.test_schema}' "
            "and tablename = 'totals' and indexname like 'dbt_mv_%'", fetch="all"
        )

    def assert_clean(self, project):
        with get_connection(project.adapter):
            schema = project.adapter.Relation.create(database=project.database, schema=project.test_schema)
            names = {r.identifier for r in project.adapter.list_relations_without_caching(schema)}
        assert not any(n.endswith(("__dbt_tmp", "__dbt_backup")) for n in names)

    def write_model(self, project, config="indexes=[]", query=None, kind="materialized_view"):
        model = MODEL.replace("INDEX_CONFIG", config).replace("materialized='materialized_view'", f"materialized='{kind}'")
        if query:
            model = model.replace("select id, value", query)
        write_file(model, project.project_root, "models", "totals.sql")

    def test_lifecycle(self, project):
        run_dbt(["seed"])
        run_dbt(["build"])
        relation = self.relation(project)
        assert relation.type == RelationType.MaterializedView
        assert relation.can_be_renamed
        assert project.run_sql(f"select count(*) from {relation}", fetch="one")[0] == 2
        assert len(self.indexes(project)) == 1
        original_indexes = self.indexes(project)
        project.run_sql(f"insert into {project.test_schema}.source_rows values (3, 300)")
        assert project.run_sql(f"select count(*) from {relation}", fetch="one")[0] == 2
        _, logs = run_dbt_and_capture(["--debug", "build", "-s", "totals"])
        assert "refresh materialized view" in logs.lower()
        assert project.run_sql(f"select count(*) from {relation}", fetch="one")[0] == 3
        assert self.indexes(project) == original_indexes
        assert project.run_sql(
            f"select ispopulated from pg_matviews where schemaname = '{project.test_schema}' and matviewname = 'totals'",
            fetch="one",
        )[0]
        self.write_model(project, "indexes=[{'columns':['id']}]", "select id, value + 10 as value")
        run_dbt(["run", "-s", "totals"])
        assert project.run_sql(f"select min(value) from {relation}", fetch="one")[0] == 100
        run_dbt(["build", "-s", "totals", "--full-refresh"])
        assert project.run_sql(f"select min(value) from {relation}", fetch="one")[0] == 110
        self.assert_clean(project)
        run_dbt(["docs", "generate"])
        catalog = json.loads((Path(project.project_root) / "target" / "catalog.json").read_text())
        node = next(n for n in catalog["nodes"].values() if n["metadata"]["name"] == "totals")
        assert node["metadata"]["type"] == "MATERIALIZED VIEW"
        assert node["metadata"]["comment"] == "Stored totals"
        assert node["columns"]["id"]["comment"] == "Row identifier"
        self.write_model(project, "indexes=[{'columns':['id'], 'unique':true}]")
        _, logs = run_dbt_and_capture(["run", "-s", "totals", "--full-refresh"], expect_pass=False)
        assert "UNIQUE indexes are not supported" in logs
        assert project.run_sql(f"select min(value) from {relation}", fetch="one")[0] == 110
        previous_indexes = self.indexes(project)
        for policy in ("fail", "continue", "apply"):
            self.write_model(project, "indexes=[{'columns':['value'], 'type':'hash'}], on_configuration_change='" + policy + "'")
            run_dbt(["run", "-s", "totals"], expect_pass=policy != "fail")
            assert len(self.indexes(project)) == 1
            if policy != "apply":
                assert self.indexes(project) == previous_indexes
            else:
                assert self.indexes(project) != previous_indexes
        self.write_model(project)
        run_dbt(["run", "-s", "totals"])
        assert self.indexes(project) == []
        self.assert_clean(project)
        for kind in ("table", "materialized_view", "view", "materialized_view"):
            self.write_model(project, kind=kind)
            run_dbt(["run", "-s", "totals"])
            assert str(self.relation(project).type) == kind
            self.assert_clean(project)
        with get_connection(project.adapter):
            project.adapter.drop_relation(self.relation(project))
        assert self.relation(project) is None

    def test_failed_refresh_and_replacement(self, project):
        self.write_model(project, query="select id, 1000 / value as value")
        run_dbt(["seed", "--full-refresh"])
        run_dbt(["run", "-s", "totals", "--full-refresh"])
        relation = self.relation(project)
        before = project.run_sql(f"select * from {relation} order by id", fetch="all")
        project.run_sql(f"update {project.test_schema}.source_rows set value = 0 where id = 1")
        _, logs = run_dbt_and_capture(["run", "-s", "totals"], expect_pass=False)
        assert "division by zero" in logs.lower()
        assert project.run_sql(f"select * from {relation} order by id", fetch="all") == before
        run_dbt(["run", "-s", "totals", "--full-refresh"], expect_pass=False)
        assert project.run_sql(f"select * from {relation} order by id", fetch="all") == before
        project.run_sql(f"update {project.test_schema}.source_rows set value = 50 where id = 1")
        run_dbt(["run", "-s", "totals", "--full-refresh"])
        self.assert_clean(project)
        assert project.run_sql(f"select value from {relation} where id = 1", fetch="one")[0] == 20

    def test_external_indexes_and_invalid_config(self, project):
        self.write_model(project, "indexes=[{'columns':['id']}, {'columns':['value']}]")
        run_dbt(["seed", "--full-refresh"])
        run_dbt(["run", "-s", "totals", "--full-refresh"])
        relation = self.relation(project)
        project.run_sql(f"create index external_idx on {relation} (id)")
        before = self.indexes(project)
        for config, message in (
            ("indexes=[{'columns':['id'], 'where':'id > 0'}]", "expression and partial"),
            ("indexes=[{'columns':[]}]", "non-empty list"),
            ("indexes=[{'columns':['id'], 'type':'gin'}]", "btree or hash"),
            ("indexes=[{'columns':['missing']}]", "missing"),
        ):
            self.write_model(project, config)
            _, logs = run_dbt_and_capture(["run", "-s", "totals"], expect_pass=False)
            assert message in logs
            assert self.indexes(project) == before
        self.write_model(project)
        run_dbt(["run", "-s", "totals"])
        assert self.indexes(project) == []
        assert project.run_sql(
            f"select count(*) from pg_indexes where schemaname = '{project.test_schema}' "
            "and tablename = 'totals' and indexname = 'external_idx'", fetch="one"
        )[0] == 1

    def test_quoted_index_columns(self, project):
        self.write_model(
            project,
            "indexes=[{'columns':['CamelCase']}], persist_docs={'columns':false}",
            'select id as "CamelCase", value',
        )
        run_dbt(["seed", "--full-refresh"])
        run_dbt(["run", "-s", "totals", "--full-refresh"])
        relation = self.relation(project)
        assert len(self.indexes(project)) == 1
        original_indexes = self.indexes(project)
        run_dbt(["run", "-s", "totals"])
        assert self.indexes(project) == original_indexes
        assert project.run_sql(f'select count("CamelCase") from {relation}', fetch="one")[0] == 2
        self.assert_clean(project)
