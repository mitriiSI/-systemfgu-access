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
from services.timetable import sync_schedule,start_sync,ensure_schedule,is_syncing
from services.teachers import teacher_list,subject_key
from database import central_db,current_faculty,current_group,group_record

@contextmanager
def db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

schedule_bp = Blueprint('schedule', __name__)

from routes.auth import get_current_member, get_personal_owner
from services.material_access import item_visible,require_item,file_visible

@schedule_bp.get('/api/schedule')
def schedule():
    group = setting('group_id')
    owner = get_personal_owner()
    with db() as c:
        days = [json.loads(r[0]) for r in c.execute('SELECT body FROM schedules WHERE group_id=? ORDER BY day', (group,))]
        files = [dict(row) for row in c.execute("SELECT id,scope,item,title,filename,size FROM files WHERE scope='lesson' ORDER BY created DESC,id") if file_visible(row,owner)]
    syncing=ensure_schedule(has_cache=bool(days))
    from services.subgroups import catalog_for
    options=catalog_for(owner,days)
    record=group_record()
    from services.import_choices import catalogue
    return jsonify(days=community.filtered_days(owner,days),files=files, updated=setting('sync_' + group), error=setting('sync_error_' + group), group=setting('group_name'), group_id=current_group(), faculty=record['faculty'], source=record['source'], syncing=syncing, subgroups=options,import_choices=catalogue(owner),has_import=bool(days or setting('personal_import:'+owner)))

@schedule_bp.post('/api/schedule/refresh')
def refresh_schedule():
    # The authenticated profile supplies the group; a request cannot fetch another one.
    start_sync(force=get_current_member()['admin'])
    return jsonify(ok=True,syncing=is_syncing())

@schedule_bp.get('/api/schedule/subgroups')
def schedule_subgroups():
    from services.subgroups import catalog_for
    return jsonify(group_id=current_group(),subjects=catalog_for(get_personal_owner(),community.official_days()))

@schedule_bp.post('/api/schedule/subgroups')
def choose_subgroups():
    from services.subgroups import save_choices
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or not isinstance(body.get('choices'),dict):abort(400)
    try:subjects=save_choices(get_personal_owner(),community.official_days(),body['choices'])
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(ok=True,group_id=current_group(),subjects=subjects)

@schedule_bp.get('/api/teacher-photos')
def teacher_photos():
    # The old catalogue has no recorded permission or license for the portraits.
    return jsonify({})

def save_content(kind, item, body, author):
    with db() as c:
        c.execute('INSERT INTO revisions(kind,item,body,author,updated) VALUES(?,?,?,?,?)', (kind, item, body, author, now()))
        c.execute('INSERT OR REPLACE INTO content VALUES(?,?,?,?,?)', (kind, item, body, author, now()))

@schedule_bp.get('/api/content')
def get_content():
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM content WHERE kind NOT IN ('teacher','schedule_event')")]
    return jsonify([row for row in rows if item_visible(row['item'],get_personal_owner())])

@schedule_bp.post('/api/content')
def change_content():
    b = request.get_json() or {}
    kind = b.get('kind')
    item = str(b.get('item', ''))[:300]
    body = str(b.get('body', ''))
    if kind not in ('homework', 'schedule', 'teacher_notice') or not item or len(body) > 20000:
        abort(400)
    m = get_current_member()
    require_item(item,get_personal_owner())
    if kind == 'teacher_notice' and (not m['admin']) and (setting('teacher_write_' + m['code'], '1') != '1'):
        abort(403)
    if kind in ('homework', 'teacher_notice') or m['admin'] or (not m.get('moderate', False)):
        save_content(kind, item, body, m['name'])
        return jsonify(status='approved')
    with db() as c:
        c.execute('INSERT INTO proposals(kind,item,body,author) VALUES(?,?,?,?)', (kind, item, body, m['name']))
    return jsonify(status='pending')

@schedule_bp.get('/api/personal')
def personal_get():
    with db() as c:
        rows = [dict(r) for r in c.execute('SELECT kind,item,body,updated FROM personal WHERE owner=? ORDER BY updated DESC', (get_personal_owner(),))]
    return jsonify(rows)

@schedule_bp.post('/api/personal')
def personal_save():
    b = request.get_json() or {}
    kind = b.get('kind')
    item = str(b.get('item', ''))[:300]
    body = str(b.get('body', ''))
    if kind not in ('teacher', 'homework', 'note') or not item or len(body) > 20000:
        abort(400)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        owner=get_personal_owner()
        if b.get('delete') is True:
            c.execute('DELETE FROM personal WHERE owner=? AND kind=? AND item=?', (get_personal_owner(), kind, item))
        else:
            exists=c.execute('SELECT 1 FROM personal WHERE owner=? AND kind=? AND item=?',(owner,kind,item)).fetchone()
            if not exists and c.execute('SELECT count(*) FROM personal WHERE owner=?',(owner,)).fetchone()[0]>=1000:
                return jsonify(error='Лимит личных записей — 1000. Удалите ненужные записи.'),400
            c.execute('INSERT OR REPLACE INTO personal VALUES(?,?,?,?,?)', (get_personal_owner(), kind, item, body, now()))
    return jsonify(ok=True)

@schedule_bp.post('/api/theme')
def save_theme():
    value = (request.get_json() or {}).get('theme')
    if value not in ('light', 'dark'):
        abort(400)
    put_setting('theme_' + get_personal_owner(), value)
    return jsonify(ok=True)

@schedule_bp.post('/api/english')
def english():
    value = str((request.get_json() or {}).get('english', ''))[:80]
    if not value:
        abort(400)
    m = get_current_member()
    if m['admin']:
        with central_db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('english_'+str(m['tg']),value))
    else:
        with central_db() as c:
            c.execute('UPDATE members SET english=? WHERE code=?', (value, m['code']))
    return jsonify(ok=True)

def event_records():
    group = setting('group_id')
    with db() as c:
        rows = c.execute("SELECT item,body FROM content WHERE kind='schedule_event'").fetchall()
    records = []
    for row in rows:
        data = json.loads(row['body'])
        if data.get('group_id') == group and not data.get('deleted'):
            records.append(dict(data, id=row['item']))
    return records

@schedule_bp.get('/api/schedule/events')
def schedule_events():
    today=datetime.now(MOSCOW).date()
    start=request.args.get('start',today.isoformat());end=request.args.get('end',(today+timedelta(days=120)).isoformat())
    try:
        first=date.fromisoformat(start);last=date.fromisoformat(end)
        if last<first or (last-first).days>730:abort(400)
    except (ValueError,TypeError):abort(400)
    return jsonify(community.events(get_personal_owner(),start,end,get_current_member()['admin']))

@schedule_bp.post('/api/schedule/events')
def save_schedule_event():
    b = request.get_json()
    if not isinstance(b, dict):
        abort(400)
    member = get_current_member()
    if b.get('delete') is True:
        data = next((event for event in event_records() if event['id'] == b.get('id')), None)
        if data is None:
            abort(404)
        if not member['admin'] and data['creator'] != get_personal_owner():
            abort(403)
        item = data.pop('id')
        data['deleted'] = True
    else:
        data = {}
        for field, limit in [('title', 200), ('date', 10), ('start', 5), ('end', 5),
                             ('room', 120), ('teacher', 200), ('description', 2000), ('type', 10)]:
            value = b.get(field, '')
            if not isinstance(value, str) or len(value) > limit:
                abort(400)
            data[field] = value.strip()
        try:data['teachers']=teacher_list(b['teachers'],strict=True) if 'teachers' in b else teacher_list(data['teacher'])
        except ValueError:abort(400)
        data['teacher']=next(iter(data['teachers']),'')
        if not data['title'] or data['type'] not in ('lesson', 'event'):
            abort(400)
        try:
            if datetime.strptime(data['date'], '%Y-%m-%d').strftime('%Y-%m-%d') != data['date']:
                abort(400)
        except ValueError:
            abort(400)
        valid_time = lambda value: re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value)
        if not valid_time(data['start']) or (data['end'] and (not valid_time(data['end']) or data['end'] <= data['start'])):
            abort(400)
        data['group_id'] = setting('group_id')
        data['creator'] = get_personal_owner()
        item = secrets.token_hex(16)
    body = json.dumps(data, ensure_ascii=False)
    if member['admin'] or not member.get('moderate', False):
        save_content('schedule_event', item, body, member['name'])
        return jsonify(status='approved', id=item)
    with db() as c:
        c.execute('INSERT INTO proposals(kind,item,body,author) VALUES(?,?,?,?)',
                  ('schedule_event', item, body, member['name']))
    return jsonify(status='pending', id=item)

from datetime import date
from services import community as community

@schedule_bp.post('/api/schedule/time')
def save_lesson_time():
    if current_faculty() not in ('fgu','fgp'):abort(400)
    body=request.get_json(silent=True)
    if not isinstance(body,dict):abort(400)
    ident=body.get('id');day=body.get('date');owner=get_personal_owner()
    if not isinstance(ident,str) or len(ident)>250:abort(400)
    try:date.fromisoformat(day)
    except (ValueError,TypeError):abort(400)
    valid={community.lesson_id(day,lesson,period) for entry in community.official_days() if entry['date']==day
           for lesson in entry.get('lessons',[]) for period in lesson.get('periods',[])}
    valid.update(event['occurrence_id'] for event in community.events(owner,day,day,get_current_member()['admin'],True))
    if ident not in valid:abort(404)
    restore=body.get('restore',False)
    if type(restore) is not bool:abort(400)
    start,end=body.get('start'),body.get('end')
    if not restore:
        if not all(isinstance(value,str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value) for value in (start,end)) or end<=start:
            return jsonify(error='Укажите начало и окончание пары; окончание должно быть позже начала.'),400
    from services.lesson_times import initialize
    with db() as c:
        initialize(c)
        if restore:c.execute('DELETE FROM lesson_times WHERE owner=? AND group_id=? AND lesson_id=?',(owner,setting('group_id'),ident))
        else:c.execute('INSERT OR REPLACE INTO lesson_times VALUES(?,?,?,?,?)',(owner,setting('group_id'),ident,start,end))
    return jsonify(ok=True)

@schedule_bp.post('/api/schedule/room')
def save_lesson_room():
    if current_faculty() not in ('fgu','fgp'):abort(400)
    body=request.get_json(silent=True)
    if not isinstance(body,dict):abort(400)
    ident=body.get('id');day=body.get('date');owner=get_personal_owner()
    if not isinstance(ident,str) or not 1<=len(ident)<=250:abort(400)
    try:date.fromisoformat(day)
    except (ValueError,TypeError):abort(400)
    valid={community.lesson_id(day,lesson,period) for entry in community.official_days() if entry['date']==day
           for lesson in entry.get('lessons',[]) for period in lesson.get('periods',[])}
    valid.update(event['occurrence_id'] for event in community.events(owner,day,day,get_current_member()['admin'],True))
    if ident not in valid:abort(404)
    restore=body.get('restore',False);room=body.get('room')
    if type(restore) is not bool:abort(400)
    if not restore and (not isinstance(room,str) or len(room)>120 or re.search(r'[\x00-\x1f\x7f]',room)):
        return jsonify(error='Укажите аудиторию или адрес длиной до 120 символов.'),400
    from services.lesson_times import initialize_rooms
    with db() as c:
        initialize_rooms(c)
        if restore:c.execute('DELETE FROM lesson_rooms WHERE owner=? AND group_id=? AND lesson_id=?',(owner,setting('group_id'),ident))
        else:c.execute('INSERT OR REPLACE INTO lesson_rooms VALUES(?,?,?,?)',(owner,setting('group_id'),ident,room.strip()))
    return jsonify(ok=True)

@schedule_bp.post('/api/schedule/hide')
def hide_occurrence():
    body=request.get_json() or {};ident=body.get('id');day=body.get('date')
    if not isinstance(ident,str) or not 1<=len(ident)<=250:abort(400)
    try:date.fromisoformat(day)
    except (ValueError,TypeError):abort(400)
    owner=get_personal_owner()
    valid={community.lesson_id(d['date'],lesson,period) for d in community.official_days() if d['date']==day for lesson in d.get('lessons',[]) for period in lesson.get('periods',[])}
    valid.update(e['occurrence_id'] for e in community.events(owner,day,day,get_current_member()['admin'],True))
    if ident not in valid:abort(404)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO hidden_lessons VALUES(?,?,?,?)',(owner,setting('group_id'),ident,now()))
        for event in community.events(owner,day,day,get_current_member()['admin'],True):
            if event['occurrence_id']==ident and event.get('source')=='custom':
                row=c.execute('SELECT * FROM custom_lessons WHERE id=? AND owner=?',(event['id'],owner)).fetchone()
                if row:
                    from services.lesson_history import record
                    record(c,row['id'],owner,'hidden',row['body'],ident)
    return jsonify(ok=True)

@schedule_bp.post('/api/schedule/restore')
def restore_personal_schedule():
    if (request.get_json() or {}).get('restore_deleted') is not True:abort(400)
    with db() as c:c.execute('DELETE FROM hidden_lessons WHERE owner=? AND group_id=?',(get_personal_owner(),setting('group_id')))
    # Restore the most recently synchronized official data immediately; refresh in the background.
    start_sync()
    return jsonify(ok=True)

@schedule_bp.post('/api/schedule/custom')
def custom_lesson():
    b=request.get_json()
    if not isinstance(b,dict):abort(400)
    owner=get_personal_owner();member=get_current_member()
    if b.get('disable') is True:
        if not isinstance(b.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',b['id']):abort(400)
        with db() as c:
            row=c.execute('SELECT * FROM custom_lessons WHERE id=? AND group_id=?',(b.get('id'),setting('group_id'))).fetchone()
            if not row:abort(404)
            if row['owner']!=owner and not (row['owner']=='*' and member['admin']):abort(403)
            c.execute('UPDATE custom_lessons SET active=0 WHERE id=?',(b['id'],))
            from services.lesson_history import record
            record(c,b['id'],owner,'deleted',row['body'])
        return jsonify(ok=True)
    data={}
    for name,limit in [('title',200),('date',10),('start',5),('end',5),('room',120),('teacher',200),('description',2000),('type',10),('recurrence',10),('visibility',10)]:
        value=b.get(name,'')
        if not isinstance(value,str) or len(value)>limit:abort(400)
        data[name]=value.strip()
    try:data['teachers']=teacher_list(b['teachers'],strict=True) if 'teachers' in b else teacher_list(data['teacher'])
    except ValueError:abort(400)
    data['teacher']=next(iter(data['teachers']),'')
    if not data['title'] or data['type'] not in ('lesson','event') or data['recurrence'] not in ('once','weekly') or data['visibility'] not in ('personal','group'):abort(400)
    try:
        if date.fromisoformat(data['date']).isoformat()!=data['date']:abort(400)
    except ValueError:abort(400)
    valid_time=lambda value:re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value)
    if not valid_time(data['start']) or (data['end'] and (not valid_time(data['end']) or data['end']<=data['start'])):abort(400)
    if data['visibility']=='group':
        if not member['admin']:abort(403)
        owner='*'
    number=b.get('number',0)
    if type(number) is not int or not 0<=number<=12:abort(400)
    data['number']=number
    with central_db() as c:
        for name in data['teachers']:c.execute('INSERT OR IGNORE INTO faculty_teachers VALUES(?,?,?,?,?)',(current_faculty(),name,'','','Вручную'))
    ident=b.get('id') or secrets.token_hex(16)
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):abort(400)
    with db() as c:
        from services.lesson_history import record
        stored=json.dumps(data,ensure_ascii=False)
        if b.get('id'):
            previous=c.execute('SELECT * FROM custom_lessons WHERE id=? AND group_id=?',(ident,setting('group_id'))).fetchone()
            if not previous:abort(404)
            if previous['owner']!=get_personal_owner() and not (previous['owner']=='*' and member['admin']):abort(403)
            record(c,ident,get_personal_owner(),'before_edit',previous['body'])
            c.execute('UPDATE custom_lessons SET body=?,owner=? WHERE id=?',(stored,owner,ident))
            action='edited'
        else:
            c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',(ident,owner,setting('group_id'),stored));action='created'
        record(c,ident,get_personal_owner(),action,stored)
    return jsonify(ok=True,id=ident)

@schedule_bp.get('/api/schedule/custom/<ident>')
def own_custom_lesson(ident):
    with db() as c:row=c.execute('SELECT body FROM custom_lessons WHERE id=? AND owner=? AND group_id=?',(ident,get_personal_owner(),setting('group_id'))).fetchone()
    if not row:abort(404)
    data=community.event_data(row['body'])
    if not data:abort(400)
    return jsonify(data|{'id':ident})

@schedule_bp.post('/api/schedule/teachers')
def save_subject_teachers():
    b=request.get_json()
    if not isinstance(b,dict):abort(400)
    title=b.get('title');restore=b.get('restore',False)
    if not isinstance(title,str) or not title.strip() or len(title)>200 or type(restore) is not bool:abort(400)
    try:names=None if restore else teacher_list(b.get('teachers'),strict=True)
    except ValueError:abort(400)
    key=subject_key(title);owner=get_personal_owner();group=setting('group_id')
    known={subject_key(p.get('disciplineFullName') or '') for day in community.official_days()
           for lesson in day.get('lessons',[]) for p in lesson.get('periods',[])}
    with db() as c:
        rows=list(c.execute("SELECT body FROM custom_lessons WHERE active=1 AND group_id=? AND owner IN (?, '*')",(group,owner)))
        rows+=list(c.execute("SELECT body FROM content WHERE kind='schedule_event'"))
    for row in rows:
        data=community.event_data(row[0])
        if data and not data.get('deleted') and data.get('group_id',group)==group:known.add(subject_key(data['title']))
    if key not in known:abort(404)
    member=get_current_member();body=json.dumps(names,ensure_ascii=False)
    if member['admin'] or not member.get('moderate',False):
        save_content('subject_teachers',key,body,member['name'])
        return jsonify(status='approved')
    with db() as c:c.execute('INSERT INTO proposals(kind,item,body,author) VALUES(?,?,?,?)',('subject_teachers',key,body,member['name']))
    return jsonify(status='pending')

from database import central_db,current_faculty

@schedule_bp.get('/api/teacher-ratings')
def teacher_ratings():
    with central_db() as c:
        rows={r['teacher']:dict(r) for r in c.execute('''SELECT teacher,COUNT(*) AS count,AVG(clarity) AS clarity,AVG(knowledge) AS knowledge,
            AVG(communication) AS communication,AVG(recommend)*100 AS recommended,AVG((clarity+knowledge+communication)/3.0) AS score
            FROM faculty_reviews WHERE faculty=? GROUP BY teacher''',(current_faculty(),))}
    return jsonify([dict(rows.get(name,{'count':0,'score':None,'clarity':None,'knowledge':None,'communication':None,'recommended':None}),teacher=name) for name in community.teacher_names(get_personal_owner())])

@schedule_bp.get('/api/teacher-reviews')
def teacher_reviews():
    teacher=request.args.get('teacher','');owner=get_personal_owner();admin=get_current_member()['admin']
    if teacher not in community.teacher_names(owner):abort(404)
    with central_db() as c:rows=list(c.execute('SELECT * FROM faculty_reviews WHERE faculty=? AND teacher=? ORDER BY updated DESC',(current_faculty(),teacher)))
    return jsonify([{'id':r['id'],'teacher':r['teacher'],'clarity':r['clarity'],'knowledge':r['knowledge'],'communication':r['communication'],
        'recommend':bool(r['recommend']),'comment':r['comment'],'author':r['author'] if r['public_author'] else 'Анонимно',
        'public_author':bool(r['public_author']),'mine':r['owner']==owner,'can_delete':r['owner']==owner or admin,'updated':r['updated']} for r in rows])

@schedule_bp.post('/api/teacher-reviews')
def save_teacher_review():
    b=request.get_json()
    if not isinstance(b,dict):abort(400)
    owner=get_personal_owner();member=get_current_member();faculty=current_faculty()
    if b.get('delete') is True:
        with central_db() as c:
            row=c.execute('SELECT owner FROM faculty_reviews WHERE faculty=? AND id=?',(faculty,b.get('id'))).fetchone()
            if not row:abort(404)
            if row['owner']!=owner and not member['admin']:abort(403)
            c.execute('DELETE FROM faculty_reviews WHERE faculty=? AND id=?',(faculty,b['id']))
        return jsonify(ok=True)
    teacher=b.get('teacher');comment=b.get('comment','')
    if not isinstance(teacher,str) or not teacher.strip() or len(teacher)>200 or not isinstance(comment,str) or len(comment)>2000:abort(400)
    teacher=teacher.strip()
    if teacher not in community.teacher_names(owner):abort(400)
    for key in ('clarity','knowledge','communication'):
        if type(b.get(key)) is not int or not 1<=b[key]<=5:abort(400)
    if type(b.get('recommend')) is not bool or type(b.get('public_author')) is not bool:abort(400)
    if b['public_author'] and b.get('author_consent') is not True:abort(400)
    from services.legal import version,archive
    from services.privacy import record_consent
    consent=archive() if b['public_author'] else ''
    with central_db() as c:
        c.execute('''INSERT INTO faculty_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(faculty,teacher,owner) DO UPDATE SET author=excluded.author,clarity=excluded.clarity,knowledge=excluded.knowledge,
            communication=excluded.communication,recommend=excluded.recommend,comment=excluded.comment,public_author=excluded.public_author,updated=excluded.updated''',
            (secrets.token_hex(16),faculty,teacher,owner,member['name'],b['clarity'],b['knowledge'],b['communication'],int(b['recommend']),comment.strip(),int(b['public_author']),now()))
        if b['public_author']:record_consent(c,owner,'public-review',consent)
    return jsonify(ok=True)

from services import webpush as webpush_service

@schedule_bp.get('/api/push')
def push_status():
    owner=get_personal_owner();ident=request.args.get('device','')
    with central_db() as c:subscribed=c.execute('SELECT id FROM web_push_devices WHERE owner=? AND id=?',(owner,ident)).fetchone() is not None
    return jsonify(public_key=webpush_service.vapid_keys()[1],subscribed=subscribed,preferences=webpush_service.preferences(owner))

@schedule_bp.post('/api/push/subscribe')
def push_subscribe():
    b=request.get_json()
    if not isinstance(b,dict):abort(400)
    try:ident=webpush_service.subscribe(get_personal_owner(),b.get('subscription'))
    except (ValueError,TypeError):abort(400)
    return jsonify(ok=True,device=ident)

@schedule_bp.post('/api/push/unsubscribe')
def push_unsubscribe():
    b=request.get_json() or {};ident=b.get('device')
    if not isinstance(ident,str) or len(ident)!=64:abort(400)
    webpush_service.unsubscribe(get_personal_owner(),ident)
    return jsonify(ok=True)

@schedule_bp.post('/api/push/preferences')
def push_preferences():
    from services.midiary import save_offsets,LESSON_OFFSETS,DEADLINE_OFFSETS
    b=request.get_json()
    if not isinstance(b,dict) or type(b.get('lessons')) is not bool or type(b.get('deadlines')) is not bool:abort(400)
    lesson=b.get('lesson_offsets',[b.get('lesson_minutes',0)]);deadline=b.get('deadline_offsets',[b.get('deadline_minutes',60)])
    # Validate both before writing either preference.
    for values,allowed in ((lesson,LESSON_OFFSETS),(deadline,DEADLINE_OFFSETS)):
        if not isinstance(values,list) or len(values)>len(allowed) or any(type(v) is not int or v not in allowed for v in values):abort(400)
    owner=get_personal_owner();save_offsets(owner,'push:lessons',lesson,LESSON_OFFSETS);save_offsets(owner,'push:deadlines',deadline,DEADLINE_OFFSETS)
    with central_db() as c:c.execute('INSERT OR REPLACE INTO web_push_preferences VALUES(?,?,?,?,?)',(owner,int(b['lessons']),int(b['deadlines']),max(lesson,default=0),max(deadline,default=0)))
    return jsonify(ok=True)

@schedule_bp.post('/api/push/test')
def push_test():
    b=request.get_json() or {};owner=get_personal_owner()
    with central_db() as c:device=c.execute('SELECT * FROM web_push_devices WHERE id=? AND owner=?',(b.get('device'),owner)).fetchone()
    if not device:abort(404)
    at=datetime.now(MOSCOW);key='test:'+str(int(at.timestamp())//60)
    state=webpush_service.deliver(dict(device),key,{'title':'Midiary','body':'Уведомления на этом устройстве подключены.','tag':'fgu-push-test','url':'/?view=profile'},at,at.timestamp()+180)
    if state=='waiting':return jsonify(error='Проверочное уведомление можно отправить раз в минуту.'),429
    if state!='sent':return jsonify(error='Сервис уведомлений не подтвердил отправку. Попробуйте позже или подключите уведомления заново.'),503
    return jsonify(ok=True)
