{# Python executes once into a permanent intermediate staging table. SQL models
   keep dbt's standard incremental implementation. No Python/input replay. #}
{% materialization incremental, adapter='redis_adbc', supported_languages=['sql', 'python'] %}
  {% if model.language == 'sql' %}
    {{ return(dbt.materialization_incremental_default()) }}
  {% endif %}
  {% set strategy = config.get('incremental_strategy') or 'default' %}
  {% if strategy not in ['default', 'append', 'delete+insert', 'merge'] %}
    {{ exceptions.raise_compiler_error('Python incremental models support append, delete+insert and merge; unsupported strategy: ' ~ strategy) }}
  {% endif %}
  {% set unique_key = config.get('unique_key') %}
  {% if strategy == 'merge' and not unique_key %}
    {{ exceptions.raise_compiler_error('Python incremental merge requires unique_key') }}
  {% endif %}
  {% set contract = config.get('contract') %}
  {% if contract and contract.enforced %}
    {{ exceptions.raise_compiler_error('Enforced contracts on Python incremental models are not supported') }}
  {% endif %}
  {% set existing = load_cached_relation(this) %}
  {% set target = this.incorporate(type='table') %}
  {% set stage = make_intermediate_relation(target) %}
  {% set backup = make_backup_relation(target, existing.type if existing else 'table') %}
  {% set replace = existing is none or not existing.is_table or should_full_refresh() %}
  {% set schema_policy = incremental_validate_on_schema_change(config.get('on_schema_change'), default='ignore') %}
  {{ drop_relation_if_exists(load_cached_relation(stage)) }}
  {{ drop_relation_if_exists(load_cached_relation(backup)) }}
  {{ run_hooks(pre_hooks, inside_transaction=False) }}
  {{ run_hooks(pre_hooks, inside_transaction=True) }}
  {% call statement('main' if replace else 'python_model', language='python') -%}
    {{- redis_adbc__py_write_table(False, stage, compiled_code) -}}
  {%- endcall %}
  {% if replace %}
    {% do create_indexes(stage) %}
    {% if existing is not none %}
      {{ adapter.rename_relation(existing, backup) }}
    {% endif %}
    {{ adapter.rename_relation(stage, target) }}
  {% else %}
    {% set dest_columns = process_schema_changes(schema_policy, stage, existing) %}
    {% if not dest_columns %}
      {% set dest_columns = adapter.get_columns_in_relation(existing) %}
    {% endif %}
    {% do adapter.expand_target_column_types(from_relation=stage, to_relation=target) %}
    {% set strategy_func = adapter.get_incremental_strategy_macro(context, strategy) %}
    {% set args = {'target_relation': target, 'temp_relation': stage, 'unique_key': unique_key,
                   'dest_columns': dest_columns,
                   'incremental_predicates': config.get('predicates', none) or config.get('incremental_predicates', none)} %}
    {% call statement('main') %}
      {{ strategy_func(args) }}
    {% endcall %}
    {{ adapter.drop_relation(stage) }}
  {% endif %}
  {% do apply_grants(target, config.get('grants'), should_revoke=replace) %}
  {% do persist_docs(target, model) %}
  {{ run_hooks(post_hooks, inside_transaction=True) }}
  {{ adapter.commit() }}
  {{ drop_relation_if_exists(load_cached_relation(backup)) }}
  {{ run_hooks(post_hooks, inside_transaction=False) }}
  {{ return({'relations': [target]}) }}
{% endmaterialization %}
