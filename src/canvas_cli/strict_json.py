"""Unambiguous JSON for API responses and immutable local snapshots."""

import json
import math


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key')
        result[key] = value
    return result


def _finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite JSON number')
    return result


def load(source):
    return json.load(source, object_pairs_hook=_object, parse_constant=_finite, parse_float=_finite)
