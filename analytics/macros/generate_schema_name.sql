{#- Use the folder's schema name exactly (staging / intermediate / marts) instead of dbt's
    default "<target schema>_<custom schema>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
