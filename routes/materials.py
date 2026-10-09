"""Diary routes restored from the original project."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from flask import Blueprint, request, jsonify, session, abort, current_app, send_from_directory
from config import BOT_TOKEN as TOKEN, ADMIN_IDS as ADMINS, get_public_url as public_url
from config import DATA_DIR as DATA, ROOT_DIR as ROOT, MOSCOW_TZ as MOSCOW
from database import get_db as _get_db, get_setting as setting, set_setting as put_setting, utc_now as now
from services.timetable import sync_schedule
from database import central_db,group_members

@contextmanager
def db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

materials_bp = Blueprint('materials', __name__)

from routes.auth import get_current_member, get_personal_owner
from services.material_access import require_item,file_visible,file_record,item_visible
from services.upload_limits import bounded_upload

@materials_bp.get('/api/topics')
def topics():
    with db() as c:
        return jsonify([dict(r) for r in c.execute('SELECT * FROM topics ORDER BY id')])

@materials_bp.post('/api/topics')
def add_topic():
    if not get_current_member()['admin']:
        abort(403)
    title = str((request.get_json() or {}).get('title', '')).strip()[:200]
    if not title:
        abort(400)
    try:
        with db() as c:
            c.execute('INSERT INTO topics(title) VALUES(?)', (title,))
    except sqlite3.IntegrityError:
        abort(409)
    return jsonify(ok=True)

@materials_bp.get('/api/files')
def files():
    from services.subgroups import lesson_items
    scope=request.args.get('scope');item=request.args.get('item','')
    owner=get_personal_owner()
    if scope=='lesson':require_item(item,owner,lesson=True)
    items=lesson_items(item) if scope=='lesson' else [item]
    placeholders=','.join('?' for _ in items)
    with db() as c:
        return jsonify([dict(r) for r in c.execute('SELECT * FROM files WHERE scope=? AND item IN ('+placeholders+') ORDER BY created DESC', (scope,*items)) if file_visible(r,owner)])

@materials_bp.post('/api/files')
@bounded_upload
def upload():
    f = request.files.get('file')
    scope = request.form.get('scope')
    item = request.form.get('item', '')[:300]
    if not f or scope not in ('lesson', 'literature', 'material') or (not item):
        abort(400)
    if scope=='lesson':require_item(item,get_personal_owner(),lesson=True)
    if scope == 'material':
        with db() as c:
            if not c.execute('SELECT id FROM material_sets WHERE id=?', (item,)).fetchone():
                abort(400)
    if scope == 'literature':
        with db() as c:
            if not c.execute('SELECT id FROM topics WHERE id=?', (item,)).fetchone():
                abort(400)
    ident = secrets.token_hex(24)
    path = DATA / 'files' / ident
    filename = (f.filename or 'Файл').replace('\\', '/').split('/')[-1][:240]
    title = request.form.get('title', '').strip()[:300] or filename
    try:
        f.save(path)
        with db() as c:
            c.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', (ident, scope, item, title, filename, get_current_member()['name'], now(), path.stat().st_size))
        from services.privacy import remember_file
        remember_file(ident,get_personal_owner())
    except Exception:
        with db() as c:c.execute('DELETE FROM files WHERE id=?',(ident,))
        path.unlink(missing_ok=True)
        raise
    return jsonify(ok=True)

@materials_bp.get('/api/files/<ident>')
def download(ident):
    row=file_record(ident,get_personal_owner())
    path=DATA/'files'/ident
    if path.is_symlink() or not path.is_file():abort(404)
    return send_from_directory(DATA / 'files', ident, as_attachment=True, download_name=row['filename'], mimetype='application/octet-stream')

@materials_bp.get('/api/teacher-permissions')
def permissions():
    if not get_current_member()['admin']:
        abort(403)
    rows=group_members()
    return jsonify([r | {'allowed': setting('teacher_write_' + r['code'], '1') == '1'} for r in rows])

@materials_bp.post('/api/teacher-permissions')
def change_permission():
    if not get_current_member()['admin']:
        abort(403)
    b = request.get_json() or {}
    if not isinstance(b.get('allowed'), bool):
        abort(400)
    if not isinstance(b.get('code'),str) or not 1<=len(b['code'])<=128:abort(400)
    with central_db() as c:
        if not c.execute('SELECT code FROM members WHERE code=?', (b.get('code'),)).fetchone():
            abort(404)
    put_setting('teacher_write_' + b['code'], '1' if b['allowed'] else '0')
    return jsonify(ok=True)

@materials_bp.get('/api/material-sets')
def sets():
    with db() as c:
        return jsonify([dict(r) for r in c.execute('SELECT * FROM material_sets ORDER BY subject,category,title')])

@materials_bp.post('/api/material-sets')
def create_set():
    b = request.get_json() or {}
    subject = str(b.get('subject', '')).strip()
    title = str(b.get('title', '')).strip()
    category = b.get('category')
    if not subject or not title or max(len(subject), len(title)) > 200 or (category not in ('notes', 'homework', 'presentations', 'projects')):
        abort(400)
    with db() as c:
        ident = c.execute('INSERT INTO material_sets(subject,category,title) VALUES(?,?,?)', (subject, category, title)).lastrowid
    return jsonify(id=ident)

@materials_bp.post('/api/material-sets/merge')
def merge_sets():
    if not get_current_member()['admin']:
        abort(403)
    b = request.get_json() or {}
    source, target = (b.get('source'), b.get('target'))
    if not isinstance(source, int) or not isinstance(target, int) or source == target:
        abort(400)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rows = list(c.execute('SELECT * FROM material_sets WHERE id IN (?,?)', (source, target)))
        if len(rows) != 2:
            abort(404)
        if rows[0]['subject'] != rows[1]['subject'] or rows[0]['category'] != rows[1]['category']:
            abort(400)
        c.execute("UPDATE files SET item=? WHERE scope='material' AND item=?", (str(target), str(source)))
        c.execute('DELETE FROM material_sets WHERE id=?', (source,))
    return jsonify(ok=True)

@materials_bp.get('/api/deadlines')
def deadlines():
    owner=get_personal_owner()
    with db() as c:
        rows = [dict(r) for r in c.execute('SELECT d.*,COALESCE(s.minutes,0) AS minutes FROM deadlines d\n            LEFT JOIN deadline_subs s ON d.item=s.item AND s.owner=? WHERE d.group_name=? ORDER BY due', (get_personal_owner(), setting('group_name')))]
    from services.midiary import offsets
    rows=[row for row in rows if item_visible(row['item'],owner)]
    for row in rows:row['offsets']=offsets(owner,'deadline:'+row['item'],[row['minutes']] if row['minutes'] else [])
    return jsonify(rows)

@materials_bp.post('/api/deadlines')
def save_deadline():
    b = request.get_json() or {}
    item = str(b.get('item', ''))
    title = str(b.get('title', '')).strip()
    if not item or len(item) > 300 or (not item.startswith(setting('group_name') + '|')):
        abort(400)
    require_item(item,get_personal_owner(),lesson=True)
    if b.get('delete') is True:
        if not get_current_member()['admin']:
            abort(403)
        with db() as c:
            c.execute('DELETE FROM deadlines WHERE item=?', (item,))
            c.execute('DELETE FROM deadline_subs WHERE item=?', (item,))
        return jsonify(ok=True)
    try:
        due = datetime.fromisoformat(str(b.get('due', '')))
        if due.tzinfo is None:
            raise ValueError()
    except ValueError:
        abort(400)
    if not title or len(title) > 300:
        abort(400)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO deadlines VALUES(?,?,?,?,?)', (item, setting('group_name'), title, due.astimezone(MOSCOW).isoformat(), now()))
    return jsonify(ok=True)


@materials_bp.post('/api/deadlines/reminder')
def subscribe():
    from services.midiary import save_offsets,DEADLINE_OFFSETS
    b=request.get_json() or {};minutes=b.get('minutes',0);values=b.get('offsets',[minutes] if minutes else [])
    require_item(b.get('item',''),get_personal_owner(),lesson=True)
    from services.max_platform import linked
    if values and not (get_current_member().get('tg') or linked(get_personal_owner())):return jsonify(error='Привяжите Telegram или MAX командой /link и своим кодом доступа.'),400
    with db() as c:
        if not c.execute('SELECT item FROM deadlines WHERE item=? AND group_name=?',(b.get('item'),setting('group_name'))).fetchone():abort(404)
    try:values=save_offsets(get_personal_owner(),'deadline:'+b['item'],values,DEADLINE_OFFSETS)
    except ValueError:abort(400)
    with db() as c:c.execute('INSERT OR REPLACE INTO deadline_subs VALUES(?,?,?)',(get_personal_owner(),b['item'],max(values,default=0)))
    return jsonify(ok=True,offsets=values)

@materials_bp.route('/api/reminders',methods=['GET','POST'])
def reminder_preferences():
    from services.midiary import offsets,save_offsets,LESSON_OFFSETS
    owner=get_personal_owner();member=get_current_member()
    from services.max_platform import linked
    is_linked=bool(member.get('tg')) or linked(owner)
    if request.method=='POST':
        b=request.get_json() or {};minutes=b.get('minutes',0);values=b.get('offsets',[minutes] if minutes else [])
        if values and not is_linked:return jsonify(error='Привяжите Telegram или MAX командой /link и своим кодом доступа.'),400
        try:values=save_offsets(owner,'telegram:lessons',values,LESSON_OFFSETS)
        except ValueError:abort(400)
        with db() as c:c.execute('INSERT OR REPLACE INTO reminder_prefs VALUES(?,?)',(owner,max(values,default=0)))
    with db() as c:row=c.execute('SELECT minutes FROM reminder_prefs WHERE owner=?',(owner,)).fetchone()
    legacy=row['minutes'] if row else 0
    return jsonify(minutes=legacy,offsets=offsets(owner,'telegram:lessons',[legacy] if legacy else []),choices=list(LESSON_OFFSETS),linked=is_linked)
