"""Searchable command help derived from the actual parser, without credentials."""

import argparse

from .capabilities import describe
from .client import CanvasError


def command_groups():
    capabilities = describe()
    groups = {'Read-only': set(), 'Canvas queries (server-side effects possible)': set(),
              'Local file writes': set(), 'Canvas writes (preview-first)': set(),
              'Authentication': {'auth'}, 'Local help': {'help', 'schema', 'capabilities', 'completion', 'complete'}}
    for field, category in [('read', 'Read-only'),
                            ('read_with_native_side_effects', 'Canvas queries (server-side effects possible)'),
                            ('local_write', 'Local file writes'),
                            ('canvas_write', 'Canvas writes (preview-first)')]:
        for label in capabilities[field]:
            groups[category].update(label.split(' (', 1)[0].split('/'))
    return groups


def command_help(root, topic=None, search=None):
    action = next(action for action in root._actions if isinstance(action, argparse._SubParsersAction))
    groups = command_groups()
    if topic and search is not None:
        raise CanvasError('Choose a command name or --search, not both')
    if topic:
        if topic not in action.choices:
            raise CanvasError('Unknown command; use help --search TEXT to discover commands')
        category = next((name for name, commands in groups.items() if topic in commands), None)
        if category is None:
            raise CanvasError('Command is missing its safety classification')
        return {'command_name': topic, 'safety': category,
                'help_text': action.choices[topic].format_help()}
    term = None
    if search is not None:
        term = search.strip().casefold()
        if not term:
            raise CanvasError('Help search cannot be empty')
    descriptions = {item.dest: item.help for item in action._choices_actions}
    rows = {}
    for name in sorted(action.choices):
        category = next((group for group, commands in groups.items() if name in commands), None)
        if category is None:
            raise CanvasError('Command is missing its safety classification')
        text = descriptions.get(name) or ''
        if term and term not in f'{name} {text} {category}'.casefold():
            continue
        rows.setdefault(category, []).append({'command': name, 'description': text})
    return {'command_index': rows, 'query': search,
            'note': 'Use help COMMAND --format brief for exact options. No credentials or network needed.'}


def _literal(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, (list, tuple)):
        return [_literal(item) for item in value]
    raise CanvasError('Parser metadata has an unsupported value type; no value was printed')


def _arguments(command):
    arguments = []
    for action in command._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) or action.help == argparse.SUPPRESS:
            continue
        row = {'destination': action.dest, 'flags': list(action.option_strings),
               'positional': not bool(action.option_strings), 'required': action.required,
               'action': type(action).__name__.lstrip('_'), 'nargs': action.nargs,
               'accumulates_values': isinstance(action, (argparse._AppendAction, argparse._AppendConstAction, argparse._CountAction)),
               'value_type': getattr(action.type, '__name__', 'string') if action.nargs != 0 else 'flag',
               'description': action.help or '', 'default_suppressed': action.default == argparse.SUPPRESS}
        if not row['default_suppressed']:
            row['default'] = _literal(action.default)
        if action.const is not None:
            row['const'] = _literal(action.const)
        if action.choices is not None:
            row['choices'] = _literal(list(action.choices))
        if action.metavar is not None:
            row['metavar'] = _literal(action.metavar)
        arguments.append(row)
    return arguments


def _parser_schema(command):
    result = {'arguments': _arguments(command),
              'mutually_exclusive_groups': [{'required': group.required,
                                              'destinations': [action.dest for action in group._group_actions]}
                                             for group in command._mutually_exclusive_groups]}
    selectors = [action for action in command._actions if isinstance(action, argparse._SubParsersAction)]
    if selectors:
        result['subcommand_selectors'] = [
            {'destination': action.dest, 'required': action.required,
             'commands': {name: _parser_schema(child) for name, child in sorted(action.choices.items())}}
            for action in selectors]
    return result


def command_schema(root, topic=None, search=None):
    index = command_help(root, topic, search)
    selector = next(action for action in root._actions if isinstance(action, argparse._SubParsersAction))
    if topic:
        selected = [(topic, index['safety'])]
    else:
        selected = sorted((row['command'], category) for category, rows in index['command_index'].items() for row in rows)
    descriptions = {item.dest: item.help for item in selector._choices_actions}
    return {'schema_version': 1, 'global_arguments': _arguments(root), 'query': search,
            'commands': [{'command': name, 'safety': safety, 'description': descriptions.get(name) or '',
                          **_parser_schema(selector.choices[name])} for name, safety in selected],
            'note': 'Offline parser syntax, not a JSON Schema standard or an authorization/execution contract. '
                    'Runtime account checks, publication rules, numeric bounds and confirmation requirements still apply. '
                    'Preview-first writes require reviewing a fresh preview, not just satisfying this argument schema. '
                    'No credentials, configuration files, account data or network are accessed.'}
