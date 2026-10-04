"""Offline shell candidates derived from argparse, never account or file contents."""

import argparse

from .client import CanvasError

_BASH = '''_canvas() {
    local candidate
    COMPREPLY=()
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && COMPREPLY+=("$candidate")
    done < <(canvas --format brief complete --cword "$COMP_CWORD" -- "${COMP_WORDS[@]}" 2>/dev/null)
}
complete -o default -F _canvas canvas
'''
_ZSH = '''_canvas() {
    local matches
    matches=$(canvas --format brief complete --cword "$((CURRENT - 1))" -- "${words[@]}" 2>/dev/null)
    if [[ -n "$matches" ]]; then
        local -a candidates
        candidates=("${(@f)matches}")
        compadd -- "${candidates[@]}"
    else
        _files
    fi
}
compdef _canvas canvas
'''


def script(shell):
    if shell not in ('bash', 'zsh'):
        raise CanvasError('Shell completion supports Bash and Zsh')
    return {'completion_shell': shell, 'completion_script': _BASH if shell == 'bash' else _ZSH,
            'note': 'Review before sourcing in your own shell. No dotfiles are edited. Zsh requires compinit first. '
                    'Each completion asks the local parser only, never Canvas or credentials. Shells may use their own filename fallback.'}


def _values(action):
    return [] if action.choices is None or action.help == argparse.SUPPRESS else [str(value) for value in action.choices if type(value) in (str, int)]


def _bounds(action):
    if action.nargs in ('*', '+', argparse.REMAINDER):
        return int(action.nargs == '+'), None
    if action.nargs == '?':
        return 0, 1
    count = 1 if action.nargs is None else action.nargs
    return count, count


def candidates(root, words, cword):
    if (not isinstance(words, list) or len(words) > 128 or type(cword) is not int or not 0 <= cword <= len(words)
            or any(not isinstance(word, str) or len(word) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in word)
                   for word in words)):
        raise CanvasError('Completion needs bounded shell words and a valid nonnegative cursor index; no inputs were logged')
    current = words[cword] if cword < len(words) else ''
    if cword == 0:
        return {'completion_candidates': ['canvas'] if 'canvas'.startswith(current) else []}
    command, used, position, pending, minimum, maximum, literal = root, set(), 0, None, 0, 0, False

    def actions():
        options = {flag: action for action in command._actions for flag in action.option_strings}
        positional = [action for action in command._actions if not action.option_strings]
        return options, positional

    def available(action):
        return (action.help != argparse.SUPPRESS and (action not in used or isinstance(action, (
            argparse._AppendAction, argparse._AppendConstAction, argparse._CountAction)))
            and not any(action in group._group_actions and any(other in used for other in group._group_actions if other is not action)
                        for group in command._mutually_exclusive_groups))

    for word in words[1:cword]:
        options, positional = actions()
        flag, separator, _ = word.partition('=')
        if pending is not None:
            # Bash's default word breaks split --choice=value into three words.
            if word == '=' and pending.option_strings and pending.choices is not None and '=' not in _values(pending):
                continue
            if minimum == 0 and not literal and (word == '--' or flag in options):
                pending = None
            else:
                minimum = max(0, minimum - 1)
                if maximum is not None:
                    maximum -= 1
                    if maximum == 0:
                        pending = None
                continue
        if word == '--' and not literal:
            literal = True
        elif not literal and flag in options:
            action = options[flag]
            used.add(action)
            minimum, maximum = _bounds(action)
            if separator:
                if maximum == 0:
                    return {'completion_candidates': []}
                minimum = max(0, minimum - 1)
                maximum = None if maximum is None else maximum - 1
            pending = action if maximum != 0 else None
        elif not literal and word.startswith('-'):
            return {'completion_candidates': []}
        elif position < len(positional):
            action = positional[position]
            if isinstance(action, argparse._SubParsersAction):
                if word not in action.choices:
                    return {'completion_candidates': []}
                command, position = action.choices[word], 0
            else:
                minimum, maximum = _bounds(action)
                if action.nargs == argparse.REMAINDER:
                    literal = True
                position += 1
                minimum = max(0, minimum - 1)
                maximum = None if maximum is None else maximum - 1
                pending = action if maximum != 0 else None
        else:
            return {'completion_candidates': []}
    options, positional = actions()
    if current == '=' and pending is not None and pending.option_strings and pending.choices is not None:
        values = ['=' + value for value in _values(pending)]
    elif '=' in current and not literal and (pending is None or minimum == 0):
        flag, _, value = current.partition('=')
        action = options.get(flag)
        values = [] if action is None or _bounds(action)[1] == 0 else [flag + '=' + item for item in _values(action) if item.startswith(value)]
    else:
        values = _values(pending) if pending is not None else []
        if pending is None and position < len(positional):
            action = positional[position]
            values += list(action.choices) if isinstance(action, argparse._SubParsersAction) else _values(action)
        if not literal and (pending is None or minimum == 0):
            values += [flag for flag, action in options.items() if available(action)]
    return {'completion_candidates': sorted({value for value in values if isinstance(value, str) and value.startswith(current)
                                             and not any(ord(char) < 32 or ord(char) == 127 for char in value)})}
