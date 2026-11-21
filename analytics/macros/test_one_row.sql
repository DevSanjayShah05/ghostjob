{#- Generic test: the model returns exactly one row. -#}
{% test exactly_one_row(model) %}
select n from (select count(*) as n from {{ model }}) as t where n <> 1
{% endtest %}
