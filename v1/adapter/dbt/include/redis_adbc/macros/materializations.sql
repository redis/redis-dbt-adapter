{#- Views, incremental models and snapshots use dbt's default
    materializations. -#}

{#- Tables: dbt's default table materialization, which also builds Python
    models. Their `main` statement runs the model in the dbt process
    (submit_python_job) and ingests its result into the intermediate table;
    the rename swap, hooks and persist_docs are the same as for SQL. -#}
{% materialization table, adapter='redis_adbc', supported_languages=['sql', 'python'] %}

  {%- set language = model['language'] -%}
  {%- set existing_relation = load_cached_relation(this) -%}
  {%- set target_relation = this.incorporate(type='table') %}
  {%- set intermediate_relation =  make_intermediate_relation(target_relation) -%}
  {%- set preexisting_intermediate_relation = load_cached_relation(intermediate_relation) -%}
  {%- set backup_relation_type = 'table' if existing_relation is none else existing_relation.type -%}
  {%- set backup_relation = make_backup_relation(target_relation, backup_relation_type) -%}
  {%- set preexisting_backup_relation = load_cached_relation(backup_relation) -%}
  {% set grant_config = config.get('grants') %}

  {{ drop_relation_if_exists(preexisting_intermediate_relation) }}
  {{ drop_relation_if_exists(preexisting_backup_relation) }}

  {{ run_hooks(pre_hooks, inside_transaction=False) }}

  -- `BEGIN` happens here:
  {{ run_hooks(pre_hooks, inside_transaction=True) }}

  -- build model
  {#- py_write_table directly, not through dbt's create_table_as, which
      would indent the model's first line. -#}
  {% call statement('main', language=language) -%}
    {%- if language == 'python' -%}
      {{- redis_adbc__py_write_table(False, intermediate_relation, compiled_code) -}}
    {%- else -%}
      {{ get_create_table_as_sql(False, intermediate_relation, sql) }}
    {%- endif %}
  {%- endcall %}

  {% do create_indexes(intermediate_relation) %}

  -- cleanup
  {% if existing_relation is not none %}
    {% set existing_relation = load_cached_relation(existing_relation) %}
    {% if existing_relation is not none %}
        {{ adapter.rename_relation(existing_relation, backup_relation) }}
    {% endif %}
  {% endif %}

  {{ adapter.rename_relation(intermediate_relation, target_relation) }}

  {{ run_hooks(post_hooks, inside_transaction=True) }}

  {% set should_revoke = should_revoke(existing_relation, full_refresh_mode=True) %}
  {% do apply_grants(target_relation, grant_config, should_revoke=should_revoke) %}

  {% do persist_docs(target_relation, model) %}

  -- `COMMIT` happens here
  {{ adapter.commit() }}

  {{ drop_relation_if_exists(backup_relation) }}

  {{ run_hooks(post_hooks, inside_transaction=False) }}

  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}

{#- Incremental models: with a unique_key the default strategy is
    delete+insert (as on Postgres), otherwise append. merge is also
    available. -#}
{% macro redis_adbc__get_incremental_default_sql(arg_dict) -%}
  {%- if arg_dict["unique_key"] -%}
    {{ return(get_incremental_delete_insert_sql(arg_dict)) }}
  {%- else -%}
    {{ return(get_incremental_append_sql(arg_dict)) }}
  {%- endif -%}
{%- endmacro %}

{#- Seeds: load the rows with ADBC bulk ingest (see load_seed_table), which
    is much faster than dbt's batched, parameterized INSERTs. -#}
{% macro redis_adbc__load_csv_rows(model, agate_table) %}
  {%- set relation = api.Relation.create(database=model['database'], schema=model['schema'], identifier=model['alias'], type='table') -%}
  {%- set n = adapter.load_seed_table(relation, agate_table) -%}
  {{ return("-- " ~ n ~ " rows loaded with ADBC bulk ingest") }}
{% endmacro %}

{#- Microbatch: each batch replaces the target's rows in its event_time
    window [event_time_start, event_time_end), then inserts the batch. The
    bounds are written like dbt's own filter on upstream refs, so the window
    deleted is exactly the one the batch was read from. -#}
{% macro redis_adbc__get_incremental_microbatch_sql(arg_dict) %}
  {%- set target = arg_dict["target_relation"] -%}
  {%- set source = arg_dict["temp_relation"] -%}
  {%- set dest_columns = arg_dict["dest_columns"] -%}
  {%- set predicates = (arg_dict.get("incremental_predicates") or []) | list -%}
  {%- set event_time = model.config.event_time -%}
  {%- if model.batch and model.batch.event_time_start -%}
    {%- do predicates.append("DBT_INTERNAL_TARGET." ~ event_time ~ " >= '" ~ model.batch.event_time_start ~ "'") -%}
  {%- endif -%}
  {%- if model.batch and model.batch.event_time_end -%}
    {%- do predicates.append("DBT_INTERNAL_TARGET." ~ event_time ~ " < '" ~ model.batch.event_time_end ~ "'") -%}
  {%- endif -%}
  {%- if not predicates -%}
    {{ exceptions.raise_compiler_error("microbatch: no batch window for " ~ target ~ "; refusing to delete every row") }}
  {%- endif -%}
  {%- set cols = get_quoted_csv(dest_columns | map(attribute="name")) %}
  delete from {{ target }} as DBT_INTERNAL_TARGET
  where {{ predicates | join("\n    and ") }};
  insert into {{ target }} ({{ cols }})
  (
    select {{ cols }} from {{ source }}
  )
{% endmacro %}

{#- A rerun refreshes the stored query. SQL definition changes require
    --full-refresh, as on dbt-postgres. Index configuration can be reconciled
    independently; all validation runs before hooks or cleanup DDL. -#}
{% materialization materialized_view, adapter='redis_adbc' %}
  {% set indexes = adapter.redis_mv_indexes(config.get('indexes', [])) %}
  {% set policy = config.get('on_configuration_change', 'apply') %}
  {% if policy not in ['apply', 'continue', 'fail'] %}
    {{ exceptions.raise_compiler_error("on_configuration_change must be apply, continue or fail") }}
  {% endif %}
  {% set existing = load_cached_relation(this) %}
  {% set target = this.incorporate(type='materialized_view') %}
  {% set intermediate = make_intermediate_relation(target) %}
  {% set backup = make_backup_relation(target, existing.type if existing else 'materialized_view') %}
  {% set replace = existing is none or not existing.is_materialized_view or should_full_refresh() %}
  {% set changes = {'create': [], 'drop': []} if replace else adapter.redis_mv_index_changes(target, indexes, invocation_id) %}
  {% set changed = changes['create'] or changes['drop'] %}
  {% if changed and policy == 'fail' %}
    {{ exceptions.raise_compiler_error("Materialized view index configuration changed; on_configuration_change is fail for " ~ target) }}
  {% endif %}
  {% if changed and policy == 'continue' %}
    {% do exceptions.warn("Materialized view index configuration changed; skipping " ~ target ~ " because on_configuration_change is continue") %}
    {% do store_raw_result(name='main', message='skip ' ~ target, code='skip', rows_affected=-1) %}
  {% else %}
    {{ drop_relation_if_exists(load_cached_relation(intermediate)) }}
    {{ drop_relation_if_exists(load_cached_relation(backup)) }}
    {{ run_hooks(pre_hooks, inside_transaction=False) }}
    {{ run_hooks(pre_hooks, inside_transaction=True) }}
    {% if replace %}
      {% call statement('main') %}
        {{ get_create_materialized_view_as_sql(intermediate, sql) }}
      {% endcall %}
      {% set changes = adapter.redis_mv_index_changes(intermediate, indexes, invocation_id) %}
      {% for ddl in changes['create'] %}
        {% do run_query(ddl) %}
      {% endfor %}
      {% if existing is not none %}
        {{ adapter.rename_relation(existing, backup) }}
      {% endif %}
      {{ adapter.rename_relation(intermediate, target) }}
    {% else %}
      {# Add indexes before removing any old ones; invalid columns preserve them. #}
      {% for ddl in changes['create'] %}
        {% do run_query(ddl) %}
      {% endfor %}
      {% call statement('main') %}
        {{ refresh_materialized_view(target) }}
      {% endcall %}
      {% for ddl in changes['drop'] %}
        {% do run_query(ddl) %}
      {% endfor %}
    {% endif %}
    {% do apply_grants(target, config.get('grants'), should_revoke=replace) %}
    {% do persist_docs(target, model) %}
    {{ run_hooks(post_hooks, inside_transaction=True) }}
    {{ adapter.commit() }}
    {{ drop_relation_if_exists(load_cached_relation(backup)) }}
    {{ run_hooks(post_hooks, inside_transaction=False) }}
  {% endif %}
  {{ return({'relations': [target]}) }}
{% endmaterialization %}

{% macro redis_adbc__get_create_materialized_view_as_sql(relation, sql) %}
  create materialized view {{ relation }} as {{ sql }}
{% endmacro %}

{% macro redis_adbc__refresh_materialized_view(relation) %}
  refresh materialized view {{ relation }}
{% endmacro %}

{#- Older dbt-adapters versions render the enum's materialized_view spelling
    directly in DROP; SQL requires two words. -#}
{% macro redis_adbc__drop_relation(relation) %}
  {% if relation.is_materialized_view %}
    {% call statement('drop_relation', auto_begin=False) %}
      drop materialized view if exists {{ relation }} cascade
    {% endcall %}
  {% else %}
    {{ default__drop_relation(relation) }}
  {% endif %}
{% endmacro %}

{#- SQLAdapter's default rename emits ALTER TABLE for every relation type. -#}
{% macro redis_adbc__rename_relation(from_relation, to_relation) %}
  {% set kind = 'materialized view' if from_relation.is_materialized_view else ('view' if from_relation.is_view else 'table') %}
  {% call statement('rename_relation') %}
    alter {{ kind }} {{ from_relation }} rename to {{ adapter.quote_as_configured(to_relation.identifier, 'identifier') }}
  {% endcall %}
{% endmacro %}

{#- Seeds: a reload without --full-refresh truncates the table, then loads
    it. With no transactions, a CSV whose columns the table doesn't have
    would leave the seed empty, so check the columns first. -#}
{% macro redis_adbc__reset_csv_table(model, full_refresh, old_relation, agate_table) %}
  {%- if not full_refresh -%}
    {%- set existing = adapter.get_columns_in_relation(old_relation) | map(attribute="name") | list -%}
    {%- for name in agate_table.column_names if name not in existing -%}
      {{ exceptions.raise_compiler_error("Seed column " ~ name ~ " is missing from " ~ old_relation ~ "; run dbt seed --full-refresh to recreate it with the CSV's columns") }}
    {%- endfor -%}
  {%- endif -%}
  {{ return(default__reset_csv_table(model, full_refresh, old_relation, agate_table)) }}
{% endmacro %}
