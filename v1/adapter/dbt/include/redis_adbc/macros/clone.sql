{# The default view fallback can otherwise build a self-referencing view on
   --full-refresh when source and target are the same. Preserve the source. #}
{% materialization clone, adapter='redis_adbc' %}
  {% do adapter.validate_clone_state(invocation_args_dict.get('state')) %}
  {% if defer_relation and this.database == defer_relation.database and
        this.schema == defer_relation.schema and this.identifier == defer_relation.identifier %}
    {% do log('Target relation and defer relation are the same, skipping clone for relation: ' ~ this, info=True) %}
    {% set existing = load_cached_relation(this) %}
    {{ return({'relations': [existing] if existing else []}) }}
  {% endif %}
  {{ return(dbt.materialization_clone_default()) }}
{% endmaterialization %}
