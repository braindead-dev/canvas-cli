"""CLI entry point; authentication, parsing, routing and presentation stay separate."""

import json
import sys

from . import auth
from .arguments import parser
from .client import CanvasError
from .dispatch import execute
from .formatting import brief


def run(args):
    if args.max_pages < 1:
        raise CanvasError('--max-pages must be positive')
    if args.command == 'help':
        from .navigation import command_help
        return command_help(parser(), args.topic, args.search)
    if args.command == 'schema':
        from .navigation import command_schema
        return command_schema(parser(), args.topic, args.search)
    if args.command == 'capabilities':
        from .capabilities import describe
        return describe()
    if args.command == 'snapshot-diff':
        from .snapshot_diff import compare, read
        return compare(read(args.older), read(args.newer))
    if args.command == 'snapshot-search':
        from .snapshot_diff import read
        from .snapshot_search import search
        return search(read(args.snapshot), args.query, args.limit)
    if args.command == 'snapshot-markdown':
        from .markdown import render, save
        from .snapshot_diff import read
        return save(args.output, render(read(args.snapshot)))
    if args.command == 'auth' and args.action == 'login':
        return auth.login(args.origin)
    if args.command == 'auth' and args.action == 'logout':
        return auth.logout()
    return execute(auth.connect(), args)


def main():
    try:
        args = parser().parse_args()
        data = run(args)
        print(brief(data) if args.format == 'brief' else json.dumps(data, indent=2))
    except CanvasError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('Error: local file/configuration operation failed; no private contents logged.', file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - suppress backend diagnostics that may contain credentials
        print('Error: credential backend or operation failed; no sensitive diagnostic output logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
