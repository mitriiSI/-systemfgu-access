"""Faculty bell times saved once; no network dependency."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ffl_times():
    return json.loads((Path(__file__).resolve().parent.parent / 'catalog' / 'ffl-bell-times.json').read_text())


def for_group(record):
    if record.get('faculty') != 'ffl':
        return []
    level = 'master' if record.get('level') in ('Магистратура', 'Аспирантура', 'Интегрированная магистратура') else 'bachelor'
    return ffl_times()[level]
