{% macro assert_query(sql, expected) %}
  {% set actual = run_query(sql).rows[0][0] %}
  {% if actual | int != expected | int %}
    {{ exceptions.raise_compiler_error('Parity assertion failed: ' ~ sql ~ '; expected ' ~ expected ~ ', got ' ~ actual) }}
  {% endif %}
{% endmacro %}

{% macro mutate_trips() %}
  {% do run_query('update ' ~ ref('trips') ~ " set zone = 'updated' where id = 1") %}
  {% do run_query('delete from ' ~ ref('trips') ~ ' where id = 2') %}
{% endmacro %}

{% macro load_parity_csv(path) %}
  {% set relation = api.Relation.create(database=target.database, schema=target.schema, identifier='csv_sample', type='table') %}
  {% set n = adapter.load_csv_file(relation, path, {'id': 'BIGINT', 'name': 'VARCHAR'}, sample_every=2, limit=2, row_number_column='file_row') %}
  {% if n != 2 %}{{ exceptions.raise_compiler_error('Expected two sampled CSV rows') }}{% endif %}
{% endmacro %}

{% macro violate_contract() %}
  {% do run_query('insert into ' ~ ref('trips_contract') ~ " (id, zone) values (null, 'invalid')") %}
{% endmacro %}

{% macro assert_exact_metadata() %}
  {% set relation = api.Relation.create(database=target.database, schema=target.schema, identifier='exact_metadata', type='table') %}
  {% do run_query('create table ' ~ relation ~ ' (amount numeric(12,2), label varchar(17), occurred timestamp(3))') %}
  {% set columns = adapter.get_columns_in_relation(relation) %}
  {% set expected = ['NUMERIC(12,2)', 'VARCHAR(17)', 'TIMESTAMP(3)'] %}
  {% if columns | length != 3 %}{{ exceptions.raise_compiler_error('Expected three exact metadata columns') }}{% endif %}
  {% for column in columns %}
    {% if column.data_type | upper | replace(' ', '') != expected[loop.index0] %}
      {{ exceptions.raise_compiler_error('Lost exact SQL declaration: ' ~ column.data_type) }}
    {% endif %}
  {% endfor %}
  {% if not columns[1].is_string() %}{{ exceptions.raise_compiler_error('VARCHAR lost string classification') }}{% endif %}
{% endmacro %}
