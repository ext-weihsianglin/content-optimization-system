"""Audited dependencies, independent of constraints on an HTML-only intervention.

The explicit registry covers the retention-based v2–v6 candidate union. New names
must be reviewed; they never silently default to document-only. A missingness
indicator inherits the dependency of the feature whose absence it records.
"""
import json
from pathlib import Path

REGISTRY = json.loads(Path(__file__).with_suffix('.json').read_text())
GROUPS = ('prompt', 'doc', 'promptXdoc')


def feature_metadata(name):
    base = name.removeprefix('missingindicator_')
    result = dict(REGISTRY[base])
    if base != name:
        result['reason'] = 'Missingness indicator for ' + base + '. ' + result['reason']
    return result


def feature_group(name):
    return feature_metadata(name)['dependency']


def fixed_for_html_edit(name):
    return feature_metadata(name)['html_edit_role'] in ('prompt fixed', 'URL fixed')
