{% macro redis_adbc__get_create_index_sql(relation, index_dict) -%}
  {{ return(adapter.redis_index_sql(relation, index_dict, invocation_id)) }}
{%- endmacro %}

{% macro redis_adbc__get_drop_index_sql(relation, index_name) -%}
  drop index if exists "{{ relation.schema | replace('"', '""') }}"."{{ index_name | replace('"', '""') }}"
{%- endmacro %}
