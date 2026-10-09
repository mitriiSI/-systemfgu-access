"""Private history points, with exact totals and optional legacy metadata."""
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, jsonify, request

from config import MOSCOW_TZ
from database import central_db, current_group, utc_now

points_bp = Blueprint('history_points', __name__)
CATEGORIES = ('seminar', 'homework', 'test', 'exam', 'other')
MAX_ENTRIES = 1000


def initialize():
    with central_db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS history_points(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, group_id TEXT NOT NULL,
            date TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
            points INTEGER NOT NULL CHECK(points BETWEEN 0 AND 100000),
            created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS history_points_owner_date
            ON history_points(owner, group_id, date);
        ''')


def semester(day):
    year = day.year - (day.month == 1)
    number = 1 if 2 <= day.month <= 8 else 2
    return f'{year}-{number}'


def term_info(term):
    if not isinstance(term, str) or not re.fullmatch(r'(?:1999|20\d{2})-[12]', term):
        abort(400, description='Выберите семестр')
    year, number = map(int, term.split('-'))
    if number == 1:
        start, end, label = date(year, 2, 1), date(year, 8, 31), f'Весна {year}'
    else:
        start, end, label = date(year, 9, 1), date(year + 1, 1, 31), f'Осень {year}'
    return {'id': term, 'label': label, 'start': start.isoformat(), 'end': end.isoformat()}


def public_entry(row):
    return {key: row[key] for key in ('id', 'date', 'category', 'title', 'created', 'updated')} | {
        'points': row['points'] / 100}


def valid_body(body):
    if not isinstance(body, dict) or set(body) - {'id', 'date', 'category', 'title', 'points'}:
        abort(400)
    cents = valid_points(body.get('points'))
    if set(body) <= {'id', 'points'}:
        return None, None, None, cents
    value = body.get('date')
    try:
        day = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        day = None
    if not day or value != day.isoformat() or not 2000 <= day.year <= 2099:
        abort(400)
    title = body.get('title')
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        abort(400)
    if any(ord(char) < 32 for char in title):
        abort(400)
    category = body.get('category')
    if not isinstance(category, str) or category not in CATEGORIES:
        abort(400)
    return day.isoformat(), category, title.strip(), cents


def valid_points(value):
    if type(value) not in (int, float):
        abort(400)
    try:
        amount = Decimal(str(value))
        scaled = amount * 100
        if not amount.is_finite() or not 0 <= amount <= 1000 or scaled != scaled.to_integral_value():
            abort(400)
        cents = int(scaled)
    except (InvalidOperation, OverflowError, ValueError):
        abort(400)
    return cents


@points_bp.get('/api/history-points')
def ledger():
    from routes.auth import get_personal_owner
    owner, group = get_personal_owner(), current_group()
    if request.args.get('simple') == '1':
        with central_db() as c:
            rows = c.execute('''SELECT id,points FROM history_points WHERE owner=? AND group_id=?
                ORDER BY created,id''', (owner, group)).fetchall()
        return jsonify(total=sum(row['points'] for row in rows) / 100,
                       entries=[{'id': row['id'], 'points': row['points'] / 100} for row in rows])
    term = term_info(request.args.get('term', semester(datetime.now(MOSCOW_TZ).date())))
    with central_db() as c:
        rows = c.execute('''SELECT * FROM history_points WHERE owner=? AND group_id=?
            AND date BETWEEN ? AND ? ORDER BY date DESC,created DESC,id DESC''',
            (owner, group, term['start'], term['end'])).fetchall()
        dates = c.execute('SELECT DISTINCT date FROM history_points WHERE owner=? AND group_id=?',
                          (owner, group)).fetchall()
    terms = sorted({semester(date.fromisoformat(row[0])) for row in dates} | {term['id']}, reverse=True)
    return jsonify(term=term, terms=[term_info(value) for value in terms],
                   total=sum(row['points'] for row in rows) / 100,
                   entries=[public_entry(row) for row in rows])


@points_bp.get('/api/history-points/summary')
def summaries():
    from routes.auth import get_personal_owner
    owner, group = get_personal_owner(), current_group()
    with central_db() as c:
        rows = c.execute('''SELECT date,SUM(points) AS points,COUNT(*) AS count FROM history_points
            WHERE owner=? AND group_id=? GROUP BY date''', (owner, group)).fetchall()
    totals = {}
    for row in rows:
        key = semester(date.fromisoformat(row['date']))
        total = totals.setdefault(key, {'term': key, 'points': 0, 'count': 0})
        total['points'] += row['points']
        total['count'] += row['count']
    return jsonify(total=sum(row['points'] for row in rows) / 100,
                   count=sum(row['count'] for row in rows),
                   totals=[{'term': key, 'total': value['points'] / 100, 'count': value['count']}
                           for key, value in sorted(totals.items(), reverse=True)])


@points_bp.post('/api/history-points')
def save():
    from routes.auth import get_personal_owner
    owner, group = get_personal_owner(), current_group()
    body = request.get_json() or {}
    values = valid_body(body)
    ident = body.get('id')
    editing = 'id' in body
    if editing and (not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident)):
        abort(400)
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT * FROM history_points WHERE id=? AND owner=? AND group_id=?',
                             (ident, owner, group)).fetchone() if editing else None
        if editing and not existing:
            abort(404)
        if values[0] is None:
            metadata = ((existing['date'], existing['category'], existing['title']) if existing else
                        (datetime.now(MOSCOW_TZ).date().isoformat(), 'other', 'Баллы'))
            values = (*metadata, values[3])
        term = term_info(semester(date.fromisoformat(values[0])))
        count = c.execute('''SELECT COUNT(*) FROM history_points WHERE owner=? AND group_id=?
            AND date BETWEEN ? AND ? AND id!=?''',
            (owner, group, term['start'], term['end'], ident or '')).fetchone()[0]
        if count >= MAX_ENTRIES:
            return jsonify(error='В этом семестре уже 1000 записей. Измените существующую запись.'), 400
        now = utc_now()
        if editing:
            c.execute('''UPDATE history_points SET date=?,category=?,title=?,points=?,updated=?
                WHERE id=? AND owner=? AND group_id=?''', (*values, now, ident, owner, group))
        else:
            ident = uuid.uuid4().hex
            c.execute('INSERT INTO history_points VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident, owner, group, *values, now, now))
        entry = public_entry(c.execute('SELECT * FROM history_points WHERE id=?', (ident,)).fetchone())
    return jsonify(ok=True, entry=entry), 200 if editing else 201


@points_bp.delete('/api/history-points/<ident>')
def remove(ident):
    from routes.auth import get_personal_owner
    owner, group = get_personal_owner(), current_group()
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        abort(404)
    with central_db() as c:
        result = c.execute('DELETE FROM history_points WHERE id=? AND owner=? AND group_id=?',
                           (ident, owner, group))
        if not result.rowcount:
            abort(404)
    return jsonify(ok=True)
