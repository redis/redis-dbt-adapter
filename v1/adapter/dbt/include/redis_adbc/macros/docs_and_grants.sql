{#- persist_docs: dbt's defaults are deliberately unimplemented. The driver
    has COMMENT ON (tables, views and columns); the comments show up in the
    docs catalog. -#}
{% macro redis_adbc__alter_relation_comment(relation, relation_comment) -%}
  comment on {{ "view" if relation.type == "view" else "table" }} {{ relation }} is {{ redis_adbc__comment_literal(relation_comment) }};
{%- endmacro %}

{% macro redis_adbc__alter_column_comment(relation, column_dict) -%}
  {%- for column_name, column in column_dict.items() %}
  comment on column {{ relation }}.{{ adapter.quote(column_name) if column.get("quote") else column_name }} is {{ redis_adbc__comment_literal(column.get("description")) }};
  {%- endfor %}
{%- endmacro %}

{#- A standard SQL string literal ('' for '; backslashes are literal). An empty
    description removes the comment. -#}
{% macro redis_adbc__comment_literal(comment) -%}
  '{{ (comment or "") | replace("'", "''") }}'
{%- endmacro %}

{#- Enforced native grants require explicit dedicated-ACL configuration.
    Unconfigured profiles retain the historical warning; no SQL is sent. -#}
{% macro redis_adbc__apply_grants(relation, grant_config, should_revoke=True) -%}
  {%- if adapter.rbac_grants_enabled() -%}
    {%- set select_grants = {} -%}
    {%- for privilege, grantees in (grant_config or {}).items() -%}
      {%- if privilege | lower != 'select' -%}
        {{ exceptions.raise_compiler_error("Redis RBAC grants support only SELECT on base tables") }}
      {%- endif -%}
      {%- do select_grants.update({'select': grantees}) -%}
    {%- endfor -%}
    {{ return(dbt.default__apply_grants(relation, select_grants, should_revoke)) }}
  {%- elif grant_config -%}
    {%- do exceptions.warn("grants are skipped for " ~ relation ~ ": configure adbc.redis.rbac for enforced native SELECT grants") -%}
  {%- endif -%}
{%- endmacro %}

{% macro redis_adbc__support_multiple_grantees_per_dcl_statement() -%}
  {{ return(False) }}
{%- endmacro %}

{% macro redis_adbc__get_show_grant_sql(relation) -%}
  select grantee, lower(privilege_type) as privilege_type
  from information_schema.role_table_grants
  where table_schema = {{ redis_adbc__comment_literal(relation.schema) }}
    and table_name = {{ redis_adbc__comment_literal(relation.identifier) }}
{%- endmacro %}

{% macro redis_adbc__get_grant_sql(relation, privilege, grantees) -%}
  grant {{ privilege }} on table {{ relation.render() }} to {{ adapter.quote(grantees[0]) }}
{%- endmacro %}

{% macro redis_adbc__get_revoke_sql(relation, privilege, grantees) -%}
  revoke {{ privilege }} on table {{ relation.render() }} from {{ adapter.quote(grantees[0]) }}
{%- endmacro %}
