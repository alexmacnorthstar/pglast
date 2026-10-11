# :Project:   pglast — PL/pgSQL body layout
# :License:   GNU General Public License version 3 or later

from .parser import scan


def format_body(source):
    """Indent procedural blocks without rewriting expressions or literal tokens.

    The PostgreSQL scanner keeps strings (including dollar quoting and continued
    string literals), quoted identifiers and comments intact. Only the whitespace
    between tokens is changed; SQL CASE expressions are not procedural blocks.
    """
    parts = []
    blocks = []
    indent = 0
    statement_start = True
    header = None
    sql_cases = 0
    parentheses = 0
    closing = False
    label = False
    directive = False
    newline = True
    end = 0

    for token in scan(source):
        text = source[token.start:token.end + 1]
        gap = source[end:token.start]
        end = token.end + 1
        word = text.upper() if token.kind != 'NO_KEYWORD' or token.name == 'IDENT' else ''
        # Quoted identifiers must never be interpreted as block delimiters.
        if text.startswith('"'):
            word = ''
        after = False
        next_indent = indent
        comment = token.name in ('SQL_COMMENT', 'C_COMMENT')

        if directive and '\n' in gap:
            statement_start = True
            directive = False
        if comment:
            after = token.name == 'SQL_COMMENT'
        elif statement_start and text == '#':
            directive = True
        elif statement_start and text == '<<':
            label = True
        elif label:
            if text == '>>':
                label = False
                after = True
        elif closing:
            pass
        elif word == 'CASE' and not statement_start:
            sql_cases += 1
        elif word == 'END' and sql_cases:
            sql_cases -= 1
        elif sql_cases or parentheses:
            pass
        elif statement_start and word in ('DECLARE', 'BEGIN'):
            if word == 'BEGIN' and blocks and blocks[-1][0] == 'DECLARE':
                _, indent = blocks.pop()
            blocks.append((word, indent))
            newline = after = True
            next_indent = indent + 1
        elif statement_start and word == 'END' and blocks:
            _, indent = blocks.pop()
            next_indent = indent
            newline = True
            closing = True
        elif statement_start and word == 'EXCEPTION' and blocks:
            indent = blocks[-1][1]
            next_indent = indent + 1
            newline = after = True
        elif statement_start and word in ('ELSE', 'ELSIF') and blocks:
            kind, base = blocks[-1]
            indent = base + (kind == 'CASE')
            newline = True
            after = word == 'ELSE'
            next_indent = indent + 1 if after else indent
            header = None if after else 'THEN'
        elif word == 'WHEN' and statement_start and blocks:
            indent = blocks[-1][1] + 1
            next_indent = indent
            newline = True
            header = 'THEN'
        elif (statement_start and word in ('IF', 'CASE', 'FOR', 'FOREACH', 'WHILE', 'LOOP')
              and (not blocks or blocks[-1][0] != 'DECLARE')):
            kind = word if word in ('IF', 'CASE') else 'LOOP'
            blocks.append((kind, indent))
            header = 'THEN' if kind == 'IF' else 'LOOP' if kind == 'LOOP' else 'WHEN'
            if word == 'LOOP':
                after = True
                next_indent = indent + 1
                header = None
        elif header == 'WHEN' and word == 'WHEN':
            indent = blocks[-1][1] + 1
            next_indent = indent
            newline = True
            header = 'THEN'
        elif header == word and header in ('THEN', 'LOOP'):
            after = True
            next_indent = indent + 1
            header = None

        if newline or '\n' in gap:
            if parts:
                parts.append('\n')
            parts.append('  ' * indent)
        else:
            parts.append(gap)
        parts.append(text)
        newline = after
        indent = next_indent

        if not comment and not label:
            if text == '(' or text == '[':
                parentheses += 1
            elif text == ')' or text == ']':
                parentheses -= 1
            if text == ';' and not parentheses:
                statement_start = True
                closing = False
                newline = True
                header = None
            elif not directive:
                statement_start = after

    return '\n' + ''.join(parts) + '\n'
