"""Ordinary keyword-named calls must survive deparsing without losing arguments."""

import pytest

from pglast import ast, enums, parse_sql
from pglast.stream import IndentedStream, RawStream


def function_format(parsed):
    statement = parsed[0].stmt
    assert isinstance(statement, ast.SelectStmt)
    assert statement.targetList
    function = statement.targetList[0].val
    assert isinstance(function, ast.FuncCall)
    return function.funcformat


@pytest.mark.parametrize('stream_class', (RawStream, IndentedStream))
@pytest.mark.parametrize('special_functions', (False, True))
@pytest.mark.parametrize('schema', ('', 'pg_catalog.', 'custom_schema.'))
@pytest.mark.parametrize('cast_arguments', (False, True))
@pytest.mark.parametrize('name,arguments', (
    ('extract', ("'epoch'", 'now()')),
    ('position', ('needle', 'haystack')),
    ('substring', ('value', '2', '4')),
    ('overlay', ('value', "'replacement'", '2', '4')),
    ('overlay', ('value', "'replacement'", '2')),
    ('trim', ('value',)),
    ('normalize', ('value', "'NFC'")),
    ('is_normalized', ('value', "'NFC'")),
))
@pytest.mark.parametrize('decoration', (
    'plain', 'distinct', 'order', 'within_group', 'filter', 'window', 'variadic', 'star',
))
def test_keyword_function_roundtrip(stream_class, special_functions, schema,
                                    cast_arguments, name, arguments, decoration):
    if cast_arguments:
        arguments = tuple(f'CAST({argument} AS text)' for argument in arguments)
    args = ', '.join(arguments)
    suffix = ''
    if decoration == 'distinct':
        args = 'DISTINCT ' + args
    elif decoration == 'order':
        args += ' ORDER BY sort_key'
    elif decoration == 'within_group':
        suffix = ' WITHIN GROUP (ORDER BY sort_key)'
    elif decoration == 'filter':
        suffix = ' FILTER (WHERE enabled)'
    elif decoration == 'window':
        suffix = ' FILTER (WHERE enabled) OVER (PARTITION BY group_key ORDER BY sort_key)'
    elif decoration == 'variadic':
        args = ', '.join((*arguments[:-1], 'VARIADIC ' + arguments[-1]))
    elif decoration == 'star':
        args = '*'
    statement = f'SELECT {schema}"{name}"({args}){suffix} FROM t'
    parsed = parse_sql(statement)
    rendered = stream_class(special_functions=special_functions)(parsed)
    reparsed = parse_sql(rendered)
    assert reparsed == parsed, rendered
    # PostgreSQL distinguishes these SQL constructs from ordinary comma calls.
    if name in ('extract', 'position'):
        assert function_format(reparsed) == (
            enums.CoercionForm.COERCE_EXPLICIT_CALL
        ), rendered


@pytest.mark.parametrize('stream_class', (RawStream, IndentedStream))
@pytest.mark.parametrize('special_functions', (False, True))
def test_extract_sql_syntax_control(stream_class, special_functions):
    parsed = parse_sql('SELECT EXTRACT(epoch FROM now())')
    rendered = stream_class(special_functions=special_functions)(parsed)
    reparsed = parse_sql(rendered)
    assert reparsed == parsed
    assert function_format(reparsed) == (
        enums.CoercionForm.COERCE_SQL_SYNTAX
    )


@pytest.mark.parametrize('stream_class', (RawStream, IndentedStream))
@pytest.mark.parametrize('special_functions', (False, True))
@pytest.mark.parametrize('statement', (
    "SELECT OVERLAY('abc' PLACING 'x' FROM 2)",
    "SELECT value IS NORMALIZED",
    "SELECT (a OR b) IS NFC NORMALIZED",
    "SELECT (value IS NULL) IS NFKC NORMALIZED",
    "SELECT pg_catalog.normalize(value)",
    "SELECT pg_catalog.is_normalized(value)",
    "SELECT pg_catalog.normalize(value, form)",
    "SELECT pg_catalog.is_normalized(value, form)",
    "SELECT pg_catalog.normalize(value, 'nfc')",
    "SELECT pg_catalog.is_normalized(value, 'invalid')",
    "SELECT pg_catalog.normalize(value, NULL)",
    "SELECT pg_catalog.is_normalized(value, 1)",
    "SELECT ts AT TIME ZONE (a + b)",
    "SELECT ts AT TIME ZONE (y AT TIME ZONE 'UTC')",
    "SELECT (a + b) AT LOCAL",
))
def test_special_function_arguments_roundtrip(stream_class, special_functions, statement):
    parsed = parse_sql(statement)
    rendered = stream_class(special_functions=special_functions)(parsed)
    assert parse_sql(rendered) == parsed, rendered
