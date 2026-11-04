"""Opt-in, real dbt SELECT grant/revoke test with provisioned Software RBAC."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import adbc_driver_manager.dbapi as dbapi
import pytest


@pytest.mark.skipif(not os.environ.get("REDIS_RBAC_TEST_CONFIG"),
                    reason="requires a dedicated Redis Software RBAC fixture")
def test_incremental_select_grant_and_revoke(tmp_path):
    # The caller provisions a dedicated role/ACL and reader, and owns cleanup.
    # Never run alongside another fixture changing database role bindings.
    config = json.loads(os.environ["REDIS_RBAC_TEST_CONFIG"])
    role = os.environ["REDIS_RBAC_TEST_ROLE"]
    reader_uri = os.environ["REDIS_RBAC_TEST_READER_URI"]
    driver = os.environ["REDIS_ADBC_DRIVER"]
    schema = "it_dbt_rbac_" + uuid4().hex[:12]
    (tmp_path / "models").mkdir()
    (tmp_path / "dbt_project.yml").write_text(
        'name: rbac_check\nversion: "1.0"\nconfig-version: 2\n'
        'profile: rbac_check\nmodel-paths: [models]\n'
    )
    (tmp_path / "profiles.yml").write_text(
        'rbac_check:\n  target: dev\n  outputs:\n    dev:\n'
        '      type: redis_adbc\n'
        '      driver: "{{ env_var(\'REDIS_ADBC_DRIVER\') }}"\n'
        '      uri: "{{ env_var(\'REDIS_URI\') }}"\n'
        f'      database: redis\n      schema: {schema}\n      threads: 1\n'
        '      driver_options:\n'
        '        adbc.redis.rbac: "{{ env_var(\'DBT_ENV_SECRET_REDIS_RBAC\') }}"\n'
    )
    model = tmp_path / "models" / "allowed.sql"
    def write_model(grants):
        model.write_text(
            "{{ config(materialized='incremental', incremental_strategy='append', grants="
            + repr(grants) + ") }}\nselect 42 as id "
            "{% if is_incremental() %} where false {% endif %}\n"
        )

    env = {**os.environ, "DBT_ENV_SECRET_REDIS_RBAC": json.dumps(config),
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DBT_PARTIAL_PARSE": "false"}
    def run(label):
        result = subprocess.run(
            [str(Path(sys.executable).parent / "dbt"), "--debug", "run", "--project-dir", str(tmp_path),
             "--profiles-dir", str(tmp_path)], env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
        (tmp_path / f"{label}.log").write_text(result.stdout)
        assert result.returncode == 0, result.stdout
        return result.stdout

    def read():
        with dbapi.connect(driver=driver, db_kwargs={"uri": reader_uri}, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT id FROM "{schema}".allowed')
                return cur.fetchall()

    try:
        write_model({"select": [role]})
        run("grant")
        deadline = time.monotonic() + 20
        while True:
            try:
                assert read() == [(42,)]
                break
            except dbapi.Error:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        assert "All grants are in place" in run("repeat")
        write_model({"select": []})
        run("revoke")
        deadline = time.monotonic() + 20
        while True:
            try:
                read()
            except dbapi.Error as err:
                assert "NOPERM" in str(err)
                break
            assert time.monotonic() < deadline, "reader retained revoked access"
            time.sleep(.1)
    finally:
        with dbapi.connect(driver=driver, db_kwargs={"uri": os.environ["REDIS_URI"]}, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
