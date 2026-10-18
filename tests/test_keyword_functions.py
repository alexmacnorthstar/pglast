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
    ('trim', ('value',)),
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
