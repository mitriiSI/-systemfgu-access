"""Owner-scoped snapshots and restoration of user-created timetable entries."""
import json

from flask import Blueprint, abort, jsonify, request

from database import get_setting, utc_now
from services.community import db, event_data

history_bp = Blueprint('lesson_history', __name__)
SCHEMA = '''CREATE TABLE IF NOT EXISTS custom_lesson_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id TEXT NOT NULL,owner TEXT NOT NULL,group_id TEXT NOT NULL,
    action TEXT NOT NULL,body TEXT NOT NULL,created TEXT NOT NULL,hidden_id TEXT NOT NULL DEFAULT '')'''


def record(c, lesson_id, owner, action, body, hidden_id='', created=None):
    c.execute(SCHEMA)
    c.execute('INSERT INTO custom_lesson_history(lesson_id,owner,group_id,action,body,created,hidden_id) VALUES(?,?,?,?,?,?,?)',
              (lesson_id, owner, get_setting('group_id'), action, body, utc_now() if created is None else created, hidden_id))


def backfill(c, owner):
    c.execute(SCHEMA)
    rows = c.execute('''SELECT * FROM custom_lessons WHERE owner=? AND group_id=? AND NOT EXISTS(
        SELECT 1 FROM custom_lesson_history h WHERE h.lesson_id=custom_lessons.id)''', (owner, get_setting('group_id'))).fetchall()
    for row in rows:
        # Old rows have no audit timestamp; do not invent a deletion or creation date.
        record(c, row['id'], owner, 'saved' if row['active'] else 'deleted', row['body'], created='')


@history_bp.get('/api/account/lesson-history')
def history():
    from routes.auth import get_personal_owner
    owner = get_personal_owner()
    group = get_setting('group_id')
    items = []
    with db() as c:
        backfill(c, owner)
        for row in c.execute('SELECT * FROM custom_lesson_history WHERE owner=? AND group_id=? ORDER BY id DESC LIMIT 100', (owner, group)):
            body = event_data(row['body'])
            current = c.execute('SELECT * FROM custom_lessons WHERE id=? AND group_id=?', (row['lesson_id'], group)).fetchone()
            if not body or not current:
                continue
            hidden = bool(row['hidden_id'] and c.execute('SELECT 1 FROM hidden_lessons WHERE owner=? AND group_id=? AND lesson_id=?', (owner, group, row['hidden_id'])).fetchone())
            can_restore = bool(not current['active'] or current['body'] != row['body'] or hidden)
            items.append({'id': row['id'], 'kind': 'custom', 'lesson_id': row['lesson_id'], 'action': row['action'],
                          'created': row['created'], 'body': body, 'hidden_date': row['hidden_id'].rsplit(':',1)[-1] if row['hidden_id'] else None,
                          'active': bool(current['active']), 'can_restore': can_restore})
        for row in c.execute("SELECT * FROM revisions WHERE kind='schedule_event' ORDER BY id DESC"):
            body = event_data(row['body'])
            if not body or body.get('creator') != owner or body.get('group_id') != group:
                continue
            current = c.execute("SELECT body FROM content WHERE kind='schedule_event' AND item=?", (row['item'],)).fetchone()
            latest = event_data(current['body']) if current else None
            restored = dict(body, deleted=False)
            items.append({'id': row['id'], 'kind': 'shared', 'lesson_id': row['item'], 'action': 'deleted' if body.get('deleted') else 'saved',
                          'created': row['updated'], 'body': body, 'active': bool(latest and not latest.get('deleted')),
                          'can_restore': bool(latest and latest.get('creator') == owner and (latest.get('deleted') or dict(latest, deleted=False) != restored))})
    items.sort(key=lambda item: (item['created'], item['id']), reverse=True)
    return jsonify(items=items[:100], group=get_setting('group_name'))


@history_bp.post('/api/account/lesson-history/restore')
def restore():
    from routes.auth import get_personal_owner, get_current_member
    owner = get_personal_owner()
    member = get_current_member()
    body = request.get_json() or {}
    ident = body.get('id')
    if type(ident) is not int or ident <= 0 or body.get('kind') not in ('custom', 'shared'):
        abort(400)
    group = get_setting('group_id')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute(SCHEMA)
        if body['kind'] == 'custom':
            row = c.execute('SELECT * FROM custom_lesson_history WHERE id=? AND owner=? AND group_id=?', (ident, owner, group)).fetchone()
            if not row:
                abort(404)
            current = c.execute('SELECT * FROM custom_lessons WHERE id=? AND group_id=?', (row['lesson_id'], group)).fetchone()
            if not current or (current['owner'] != owner and not (current['owner'] == '*' and member['admin'])):
                abort(403)
            data=event_data(row['body'])
            if not data:
                abort(400)
            if data.get('visibility')=='group' and not member['admin']:abort(403)
            restored_owner='*' if data.get('visibility')=='group' else owner
            c.execute('UPDATE custom_lessons SET body=?,owner=?,active=1 WHERE id=?', (row['body'], restored_owner, row['lesson_id']))
            if row['hidden_id']:
                c.execute('DELETE FROM hidden_lessons WHERE owner=? AND group_id=? AND lesson_id=?', (owner, group, row['hidden_id']))
            record(c, row['lesson_id'], owner, 'restored', row['body'])
            return jsonify(ok=True, status='approved')
        row = c.execute("SELECT * FROM revisions WHERE kind='schedule_event' AND id=?", (ident,)).fetchone()
        data = event_data(row['body']) if row else None
        if not data or data.get('creator') != owner or data.get('group_id') != group:
            abort(404)
        current = c.execute("SELECT body FROM content WHERE kind='schedule_event' AND item=?", (row['item'],)).fetchone()
        latest = event_data(current['body']) if current else None
        if not latest or latest.get('creator') != owner:
            abort(403)
        data['deleted'] = False
        restored = json.dumps(data, ensure_ascii=False)
        if not member['admin'] and member.get('moderate', False):
            c.execute('INSERT INTO proposals(kind,item,body,author) VALUES(?,?,?,?)', ('schedule_event', row['item'], restored, member['name']))
            return jsonify(status='pending')
        # Use this connection to keep restoration and its revision atomic.
        c.execute('INSERT OR REPLACE INTO content VALUES(?,?,?,?,?)', ('schedule_event', row['item'], restored, member['name'], utc_now()))
        c.execute('INSERT INTO revisions(kind,item,body,author,updated) VALUES(?,?,?,?,?)', ('schedule_event', row['item'], restored, member['name'], utc_now()))
    return jsonify(ok=True, status='approved')
