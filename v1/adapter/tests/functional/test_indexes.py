"""Named SQL indexes through the native ADBC table/incremental lifecycle."""

import pytest

from dbt.tests.util import get_connection, relation_from_name, run_dbt, run_dbt_and_capture, write_file


MODEL = """
{{ config(materialized=var('materialization', 'table'), unique_key='id',
          indexes=var('indexes', [{'columns': ['name'], 'type': 'btree'},
                                  {'columns': ['id', 'name'], 'type': 'hash'}])) }}
select 1 as id, 'one' as name union all select 2 as id, 'two' as name
"""


class TestIndexes:
    @pytest.fixture(scope="class")
    def models(self):
        return {"indexed.sql": MODEL}

    def named_indexes(self, project, table="indexed"):
        return project.run_sql(
            f"select indexname, indexdef from pg_indexes "
            f"where schemaname='{project.test_schema}' and tablename='{table}' "
            "and indexname like 'dbt_idx_%' order by indexdef",
            fetch="all",
        )

    def check_indexes(self, project):
        rows = [(name, definition.replace('"', ''))
                for name, definition in self.named_indexes(project)]
        assert len(rows) == 2
        assert any('(name)' in definition for _, definition in rows)
        assert any('(id, name)' in definition for _, definition in rows)
        for name, definition in rows:
            assert f"{project.test_schema}.indexed " in definition
            catalog = project.run_sql(
                "select i.indisunique, i.indisvalid, i.indnatts, "
                "pg_get_indexdef(i.indexrelid, 1, true) "
                "from pg_index i join pg_class c on c.oid=i.indexrelid "
                "join pg_namespace n on n.oid=c.relnamespace "
                f"where c.relname='{name}' and n.nspname='{project.test_schema}'",
                fetch="all",
            )
            assert len(catalog) == 1
            unique, valid, count, first = catalog[0]
            assert not unique and valid
            assert (count, first.replace('"', '')) == ((2, 'id') if '(id, name)' in definition else (1, 'name'))
        assert project.run_sql(
            f"select id from {project.test_schema}.indexed where name='two'", fetch="all"
        ) == [(2,)]
        assert self.named_indexes(project, "indexed__dbt_tmp") == []
        assert self.named_indexes(project, "indexed__dbt_backup") == []
        return {name for name, _ in rows}

    @pytest.mark.parametrize("materialization", ["table", "incremental"])
    def test_build_rebuild_and_cleanup(self, project, materialization):
        args = ["--vars", f"{{materialization: {materialization}}}"]
        run_dbt(["build", "--full-refresh", *args])
        first = self.check_indexes(project)
        run_dbt(["build", *args])
        second = self.check_indexes(project)
        if materialization == "table":
            assert first.isdisjoint(second)
        else:
            assert first == second
        run_dbt(["build", "--full-refresh", *args])
        third = self.check_indexes(project)
        assert second.isdisjoint(third)
        # All retired SQL names are gone from the entire schema.
        all_names = project.run_sql(
            f"select indexname from pg_indexes where schemaname='{project.test_schema}' "
            "and indexname like 'dbt_idx_%'", fetch="all"
        )
        assert {r[0] for r in all_names} == third

    def test_if_not_exists_and_drop(self, project):
        run_dbt(["build"])
        with get_connection(project.adapter):
            relation = relation_from_name(project.adapter, "indexed")
            sql = project.adapter.execute_macro(
                "get_create_index_sql",
                kwargs={"relation": relation, "index_dict": {"columns": ["name"]}},
            )
            project.adapter.execute(sql)
            project.adapter.execute(sql)
        rows = self.named_indexes(project)
        assert len(rows) == 3
        name = sql.split('"')[1]
        with get_connection(project.adapter):
            drop = project.adapter.execute_macro(
                "get_drop_index_sql", kwargs={"relation": relation, "index_name": name}
            )
            project.adapter.execute(drop)
            project.adapter.execute(drop)
        assert len(self.named_indexes(project)) == 2
        assert project.run_sql(
            f"select id from {project.test_schema}.indexed where name='one'", fetch="all"
        ) == [(1,)]
        project.run_sql(f"drop table {project.test_schema}.indexed")
        assert self.named_indexes(project) == []

    def test_replace_configuration(self, project):
        run_dbt(["build"])
        old_names = self.check_indexes(project)
        run_dbt(["build", "--vars", "{indexes: [{columns: [id], unique: false}]}"])
        rows = self.named_indexes(project)
        assert len(rows) == 1
        assert rows[0][0] not in old_names
        assert '(id)' in rows[0][1].replace('"', '')
        run_dbt(["build", "--vars", "{indexes: []}"])
        assert self.named_indexes(project) == []


class TestIndexesRenameRekey(TestIndexes):
    @pytest.fixture(scope="class")
    def dbt_profile_target(self, dbt_profile_target):
        return dict(dbt_profile_target, rename_rekey=True)


class TestInvalidIndexes:
    @pytest.fixture(scope="class")
    def models(self):
        return {"indexed.sql": MODEL}

    @pytest.mark.parametrize("config, message", [
        ({"columns": ["name"], "unique": True}, "UNIQUE indexes are not supported"),
        ({"columns": ["lower(name)"]}, "expression indexes are not supported"),
        ({"columns": ["name"], "where": "id > 0"}, "partial indexes are not supported"),
        ({"columns": ["name"], "type": "gin"}, "type must be 'btree' or 'hash'"),
        ({"columns": []}, "columns must be a non-empty list"),
        ({"columns": "name"}, "columns must be a non-empty list"),
        ({"columns": ["missing"]}, "columns must name existing columns"),
        ("name", "each index must be a dictionary"),
    ])
    def test_reject_invalid_config(self, project, config, message):
        write_file("{{ config(materialized='table', indexes=" + repr([config]) + ") }}\n"
                   "select 1 as id, 'one' as name", project.project_root, "models", "indexed.sql")
        results, output = run_dbt_and_capture(["build"], expect_pass=False)
        assert len(results) == 1
        assert results[0].status == "error"
        assert message in output
