# -*- coding: utf-8 -*-
# :Project:   pglast — Tests on the stream.py module
# :Created:   sab 05 ago 2017 10:31:23 CEST
# :Author:    Lele Gaifax <lele@metapensiero.it>
# :License:   GNU General Public License version 3 or later
# :Copyright: © 2017, 2018, 2019, 2021, 2022, 2024, 2026 Lele Gaifax
#

import pytest

from pglast import ast, parse_plpgsql, parse_sql
from pglast.parser import ParseError, scan
from pglast.printers import NODE_PRINTERS, PrinterAlreadyPresentError, SPECIAL_FUNCTIONS
from pglast.printers import node_printer, special_function
from pglast.stream import IndentedStream, OutputStream, RawStream


def test_output_stream():
    output = OutputStream()
    output.writes('SELECT *')
    output.writes(' FROM')
    output.writes('table ')
    output.writes('WHERE')
    output.write('id = 1')

    assert output.getvalue() == 'SELECT * FROM table WHERE id = 1'


def test_raw_stream_with_sql():
    raw_stmt_printer = NODE_PRINTERS.pop(ast.RawStmt, None)
    try:
        @node_printer(ast.RawStmt)
        def raw_stmt(node, output):
            output.write('Yeah')

        output = RawStream()
        result = output('SELECT 1; SELECT 2')
        assert result == 'Yeah; Yeah'
    finally:
        if raw_stmt_printer is not None:
            NODE_PRINTERS[ast.RawStmt] = raw_stmt_printer
        else:
            NODE_PRINTERS.pop(ast.RawStmt, None)


def test_raw_stream_with_empty_sql():
    output = RawStream()
    result = output('')
    assert result == ''
    result = output(' ')
    assert result == ''
    result = output(())
    assert result == ''


def test_raw_stream():
    raw_stmt_printer = NODE_PRINTERS.pop(ast.RawStmt, None)
    try:
        @node_printer(ast.RawStmt)
        def raw_stmt(node, output):
            output.write('Yeah')

        root = parse_sql('SELECT 1')
        output = RawStream()
        result = output(root)
        assert result == 'Yeah'
    finally:
        if raw_stmt_printer is not None:
            NODE_PRINTERS[ast.RawStmt] = raw_stmt_printer
        else:
            NODE_PRINTERS.pop(ast.RawStmt, None)


def test_raw_stream_invalid_call():
    with pytest.raises(ValueError):
        RawStream()(1)
    with pytest.raises(ValueError):
        RawStream()((1,))


def test_indented_stream_with_sql():
    raw_stmt_printer = NODE_PRINTERS.pop(ast.RawStmt, None)
    try:
        @node_printer(ast.RawStmt)
        def raw_stmt(node, output):
            output.write('Yeah')

        output = IndentedStream()
        result = output('SELECT 1; SELECT 2')
        assert result == 'Yeah;\n\nYeah'

        output = IndentedStream(separate_statements=False)
        result = output('SELECT 1; SELECT 2')
        assert result == 'Yeah;\nYeah'
    finally:
        if raw_stmt_printer is not None:
            NODE_PRINTERS[ast.RawStmt] = raw_stmt_printer
        else:
            NODE_PRINTERS.pop(ast.RawStmt, None)


@pytest.mark.parametrize('sql,threshold,expected', (
    ("SELECT 'abc\\'", 4, "SELECT 'abc\\'"),
    ("SELECT 'abc\\'", 3, "SELECT 'abc'\n       '\\'"),
    (r"SELECT 'abc\\'", 3, "SELECT 'abc'\n       '\\\\'"),
    ("SELECT 'abc\n\\'", 3, "SELECT E'abc'\n        '\\n\\\\'"),
))
def test_split_string_literals_ending_in_backslash(sql, threshold, expected):
    result = IndentedStream(split_string_literals_threshold=threshold)(parse_sql(sql))

    assert result == expected


def test_separate_statements():
    """Separate statements by ``separate_statements`` (int) newlines."""
    raw_stmt_printer = NODE_PRINTERS.pop(ast.RawStmt, None)
    try:
        @node_printer(ast.RawStmt)
        def raw_stmt(node, output):
            output.write('Yeah')

        output = IndentedStream(separate_statements=2)
        result = output('SELECT 1; SELECT 2')
        assert result == 'Yeah;\n\n\nYeah'
    finally:
        if raw_stmt_printer is not None:
            NODE_PRINTERS[ast.RawStmt] = raw_stmt_printer
        else:
            NODE_PRINTERS.pop(ast.RawStmt, None)


def test_special_function():
    output = RawStream(special_functions=True)

    assert output.get_printer_for_function('foo.test_function') is None

    try:
        @special_function('foo.test_function')
        def test(node, output):
            pass

        assert output.get_printer_for_function('foo.test_function') is test

        with pytest.raises(PrinterAlreadyPresentError):
            @special_function('foo.test_function')
            def test1(node, output):
                pass

        @special_function('foo.test_function', override=True)
        def test_function(node, output):
            output.print_list(node.args, '-')

        result = output('SELECT foo.test_function(x, "Y") FROM sometable')
        assert result == 'SELECT x - "Y" FROM sometable'
    finally:
        SPECIAL_FUNCTIONS.pop('foo.test_function')


@pytest.mark.parametrize('stream_class,expected', (
    (RawStream, 'CREATE FUNCTION f(x integer) RETURNS integer AS $$'),
    (IndentedStream, 'CREATE FUNCTION f(x integer)\nRETURNS integer\nAS $$'),
))
def test_stream_with_plpgsql_function(stream_class, expected):
    sql = ('create function f(x integer) returns integer as $body$'
           'BEGIN RETURN x + 1; END;$body$ language plpgsql')
    result = stream_class()(sql, plpgsql=True)
    separator = '\n' if stream_class is IndentedStream else ' '
    assert result == (expected + '\nBEGIN\n  RETURN x + 1;\nEND;\n$$'
                      + separator + 'LANGUAGE plpgsql')


@pytest.mark.parametrize('stream_class', (RawStream, IndentedStream))
@pytest.mark.parametrize('sql,expected', (
    ("create procedure p() language plpgsql as $$BEGIN RAISE NOTICE 'a;b'; END;$$",
     "\nBEGIN\n  RAISE NOTICE 'a;b';\nEND;\n"),
    ('do $$BEGIN PERFORM 1; END;$$', '\nBEGIN\n  PERFORM 1;\nEND;\n'),
))
def test_stream_with_plpgsql_procedure_and_do(stream_class, sql, expected):
    result = stream_class()(sql, plpgsql=True)
    assert '$$' + expected + '$$' in result
    assert parse_plpgsql(result)


@pytest.mark.parametrize('stream_class', (RawStream, IndentedStream))
def test_stream_with_invalid_plpgsql_body(stream_class):
    sql = 'do $$BEGIN not valid plpgsql; END;$$'
    # SQL parsing alone treats the body as an opaque string.
    assert stream_class()(sql)
    with pytest.raises(ParseError):
        stream_class()(sql, plpgsql=True)


@pytest.mark.parametrize('body,expected', (
    (('DECLARE i integer; BEGIN FOR i IN 1..3 LOOP IF i=1 THEN NULL; '
     'ELSIF i=2 THEN NULL; ELSE NULL; END IF; END LOOP; RETURN i; END;'),
     """DECLARE
  i integer;
BEGIN
  FOR i IN 1..3 LOOP
    IF i=1 THEN
      NULL;
    ELSIF i=2 THEN
      NULL;
    ELSE
      NULL;
    END IF;
  END LOOP;
  RETURN i;
END;"""),
    (('BEGIN CASE x WHEN 1 THEN RETURN CASE WHEN x=1 THEN 2 ELSE 3 END; '
     'WHEN 2 THEN RETURN 2; ELSE RETURN 0; END CASE; END;'),
     """BEGIN
  CASE x
    WHEN 1 THEN
      RETURN CASE WHEN x=1 THEN 2 ELSE 3 END;
    WHEN 2 THEN
      RETURN 2;
    ELSE
      RETURN 0;
  END CASE;
END;"""),
    (('BEGIN <<inner_block>> DECLARE i integer; BEGIN NULL; '
     'EXCEPTION WHEN OTHERS THEN NULL; END inner_block; RETURN 1; END;'),
     """BEGIN
  <<inner_block>>
  DECLARE
    i integer;
  BEGIN
    NULL;
  EXCEPTION
    WHEN OTHERS THEN
      NULL;
  END inner_block;
  RETURN 1;
END;"""),
    (('DECLARE i integer; BEGIN FOREACH i IN ARRAY ARRAY[1,2] LOOP NULL; END LOOP; '
     'WHILE false LOOP NULL; END LOOP; LOOP EXIT; END LOOP; RETURN 0; END;'),
     """DECLARE
  i integer;
BEGIN
  FOREACH i IN ARRAY ARRAY[1,2] LOOP
    NULL;
  END LOOP;
  WHILE false LOOP
    NULL;
  END LOOP;
  LOOP
    EXIT;
  END LOOP;
  RETURN 0;
END;"""),
))
def test_plpgsql_block_layout(body, expected):
    sql = ('CREATE FUNCTION f(x integer) RETURNS integer AS $body$'
           + body + '$body$ LANGUAGE plpgsql')
    result = IndentedStream()(sql, plpgsql=True)
    assert '$$\n' + expected + '\n$$' in result
    assert parse_plpgsql(result)
    assert IndentedStream()(result, plpgsql=True) == result


def test_plpgsql_preserves_tokens_and_other_languages():
    body = """#variable_conflict use_variable
DECLARE "begin" text := 'é'; BEGIN -- END IF; stays a comment
/* BEGIN; nested /* END; */ comment */
RAISE NOTICE 'first'
'second';
"begin" := $nested$BEGIN; END; -- literal$nested$;
RETURN x; END;"""
    sql = ('CREATE FUNCTION f(x integer) RETURNS integer AS $body$' + body
           + '$body$ LANGUAGE plpgsql; '
           'CREATE FUNCTION g() RETURNS integer AS $$select 1$$ LANGUAGE sql;')
    result = IndentedStream()(sql, plpgsql=True)
    statements = parse_sql(result)
    node = statements[0].stmt
    assert isinstance(node, ast.CreateFunctionStmt)
    assert node.options is not None
    formatted = next(option.arg[0].sval for option in node.options
                     if option.defname == 'as' and isinstance(option.arg, tuple))
    assert isinstance(formatted, str)
    assert [(token.name, body[token.start:token.end + 1]) for token in scan(body)] == [
        (token.name, formatted[token.start:token.end + 1]) for token in scan(formatted)]
    assert '$$select 1$$' in result
    assert parse_plpgsql(result)
    assert IndentedStream()(result, plpgsql=True) == result
    # Formatting bodies is opt-in.
    assert body in IndentedStream()(sql)
