"""Searchable command help derived from the actual parser, without credentials."""

import argparse

from .capabilities import describe
from .client import CanvasError


def command_groups():
    capabilities = describe()
    groups = {'Read-only': set(), 'Canvas GET (server-side effects possible)': set(),
              'Local file writes': set(), 'Canvas writes (preview-first)': set(),
              'Authentication': {'auth'}, 'Local help': {'help', 'capabilities'}}
    for field, category in [('read', 'Read-only'),
                            ('read_with_native_side_effects', 'Canvas GET (server-side effects possible)'),
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
