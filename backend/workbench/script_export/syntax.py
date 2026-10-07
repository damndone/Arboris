"""Closed syntax and literal encoding for local export targets."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from workbench.script_export.plan import ScriptExportRefusal


def refuse(message, code='INVALID_EXPORT_INPUT'):
    raise ScriptExportRefusal(code, message)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value) or len(value) > 32:
        refuse(f'Unsafe or unsupported column name: {value!r}')
    return value


def filename(value):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]*', value) or value in {'.', '..'}:
        refuse('Unsafe local filename')
    return value


def comment(value):
    return str(value).replace('\r', ' ').replace('\n', ' ').replace('\x00', ' ')


def literal(value, language):
    if isinstance(value, Mapping):
        if language == 'r':
            return 'list(' + ', '.join(f'{json.dumps(str(k))}={literal(v, language)}' for k,v in value.items()) + ')'
        return repr(dict(value)) if language == 'python' else refuse('Object is not a Stata literal')
    if isinstance(value, (list, tuple)):
        if language == 'r':
            return 'c(' + ', '.join(literal(v, language) for v in value) + ')'
        return repr(list(value)) if language == 'python' else refuse('List is not a Stata literal')
    if value is None:
        return {'python': 'None', 'r': 'NA', 'stata': '.'}[language]
    if isinstance(value, bool):
        return {'python': str(value), 'r': str(value).upper(), 'stata': str(int(value))}[language]
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            refuse('Export numbers must be finite')
        return repr(value)
    if not isinstance(value, str):
        refuse('Unsupported literal type')
    if language == 'stata':
        if any(c in value for c in '\n\r\x00"`$'):
            refuse('Unsafe Stata string literal')
        return '"' + value + '"'
    return repr(value) if language == 'python' else json.dumps(value, ensure_ascii=False)


def arithmetic(text, language, parameter):
    """Compile the closed nlcom arithmetic grammar, never evaluate input code."""
    import ast
    if not isinstance(text,str) or len(text)>500:refuse('Invalid nlcom expression')
    try:tree=ast.parse(text.strip(),mode='eval')
    except SyntaxError:refuse('Invalid nlcom expression')
    def walk(node):
        if isinstance(node,ast.Constant) and isinstance(node.value,(float,int)) and not isinstance(node.value,bool):return literal(node.value,language)
        if isinstance(node,ast.Name):return parameter(node.id)
        if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id=='b' and isinstance(node.slice,ast.Constant) and isinstance(node.slice.value,str):return parameter(node.slice.value)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):return '('+('+' if isinstance(node.op,ast.UAdd) else '-')+walk(node.operand)+')'
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
            operators={ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.Div:'/',ast.Pow:'**' if language=='python' else '^'}
            return '('+walk(node.left)+operators[type(node.op)]+walk(node.right)+')'
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'exp','log','sqrt'} and len(node.args)==1 and not node.keywords:
            function=('np.' if language=='python' else '')+node.func.id
            return function+'('+walk(node.args[0])+')'
        refuse('Only parameter arithmetic and exp/log/sqrt are permitted')
    return walk(tree.body)
