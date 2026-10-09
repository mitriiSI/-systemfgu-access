"""Apply personal-lesson ownership to its files, homework and deadlines."""
import json
import re
from flask import g, has_request_context, abort
from database import get_db, get_setting, current_group


def _lesson_owners():
    key = current_group()
    if has_request_context() and g.get('material_access_group') == key:
        return g.material_access_owners
    c = get_db()
    try:
        owners = {r['id']: r['owner'] for r in c.execute('SELECT id,owner FROM custom_lessons WHERE group_id=?', (get_setting('group_id'),))}
        for row in c.execute("SELECT item,body FROM content WHERE kind='schedule_event'"):
            try:
                body = json.loads(row['body'])
                if body.get('group_id') == get_setting('group_id'):
                    owners.setdefault(row['item'], '*')
            except (ValueError, AttributeError):
                continue
    finally:
        c.close()
    if has_request_context():
        g.material_access_group = key
        g.material_access_owners = owners
    return owners


def item_visible(item, owner):
    parts = str(item).split('|')
    if len(parts) < 3 or parts[2] != 'extra':
        return True
    if len(parts) != 4 or parts[0] != get_setting('group_name'):
        return False
    stored = _lesson_owners().get(parts[3])
    return stored in (owner, '*')


def require_item(item, owner, lesson=False):
    if lesson and (not isinstance(item, str) or not item.startswith(get_setting('group_name') + '|') or len(item) > 300):
        abort(400)
    if not item_visible(item, owner):
        abort(404)


def file_visible(row, owner):
    return row['scope'] != 'lesson' or item_visible(row['item'], owner)


def file_record(ident, owner):
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{48}', ident):
        abort(404)
    c = get_db()
    try:
        row = c.execute('SELECT * FROM files WHERE id=?', (ident,)).fetchone()
    finally:
        c.close()
    if not row or not file_visible(row, owner):
        abort(404)
    return dict(row)
