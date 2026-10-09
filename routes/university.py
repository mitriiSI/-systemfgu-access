"""Public faculty catalogue and authenticated study-group selection."""
import hashlib,json,re,secrets,threading
from flask import Blueprint,request,jsonify,abort
from database import central_db,owner_profile,group_record,initialize_group,utc_now,upsert_external_groups
from routes.auth import get_personal_owner,get_current_member

university_bp=Blueprint('university',__name__)
_catalogue_fetch=threading.Lock()
FACULTIES=[{'id':'fgu','name':'Факультет государственного управления','short':'ФГУ','diary':'Дневник ФГУ','logo':'/static/midiary-logo.svg','source':'fgu'},
           {'id':'geo','name':'Географический факультет','short':'Геофак','diary':'Дневник геофака','logo':'/static/midiary-logo.svg','source':'geo'},
           {'id':'ffl','name':'Факультет иностранных языков и регионоведения','short':'ФИЯР','diary':'Дневник ФИЯР','logo':'/static/faculties/midiary-ffl.svg','source':'excel'},
           {'id':'fgp','name':'Факультет глобальных процессов','short':'ФГП','diary':'Дневник ФГП','logo':'/static/faculties/midiary-fgp.svg','source':'excel'}]

@university_bp.get('/api/faculties')
def faculties():return jsonify(FACULTIES)

@university_bp.get('/api/groups')
def groups():
    from services.security import client_address,limit
    limit('catalogue',client_address(),60,60)
    faculty=request.args.get('faculty','fgu')
    if faculty not in ('fgu','geo','hist','ffl','fgp'):abort(400)
    catalogue=request.args.get('admin')=='1'
    if catalogue and not get_current_member()['admin']:abort(403)
    with central_db() as c:has_cached=bool(c.execute('SELECT 1 FROM university_groups WHERE faculty=? LIMIT 1',(faculty,)).fetchone())
    if faculty in ('geo','hist') and (catalogue or not has_cached):
        if _catalogue_fetch.acquire(blocking=False):
            try:
                from services.external_schedules import geo_data,hist_groups
                rows=geo_data()[0] if faculty=='geo' else hist_groups()
                upsert_external_groups(rows)
            except Exception:
                if not has_cached:return jsonify(error='Источник расписания временно недоступен. Попробуйте позже.'),503
            finally:_catalogue_fetch.release()
        elif not has_cached:return jsonify(error='Каталог групп загружается. Повторите попытку позже.'),503
    with central_db() as c:rows=[{k:r[k] for k in ('id','name','level','course','source','program')} for r in c.execute('''SELECT g.*,COALESCE(p.program,'') AS program FROM university_groups g
        LEFT JOIN university_group_programs p ON p.group_id=g.id WHERE g.faculty=? AND (? OR g.faculty<>'fgu' OR g.id='fgu:1457') ORDER BY g.level,g.course,p.program,g.name''',(faculty,catalogue))]
    return jsonify(rows)

@university_bp.post('/api/study-group')
def choose_group():
    member=get_current_member()
    b=request.get_json()
    if not isinstance(b,dict) or b.get('faculty') not in ('fgu','geo','hist','ffl','fgp'):abort(400)
    owner=get_personal_owner();faculty=b['faculty'];key=b.get('group')
    if not key and faculty in ('ffl','fgp') and isinstance(b.get('group_name'),str):
        name=' '.join(b['group_name'].split());program=b.get('program','');level=b.get('level');course=b.get('course')
        if not 1<=len(name)<=120 or not isinstance(program,str) or len(program)>200 or level not in ('Бакалавриат','Магистратура','Специалитет') or type(course) is not int or not 1<=course<=6:abort(400)
        key=faculty+':custom:'+hashlib.sha256(json.dumps([name.casefold(),level,course,program.casefold()],ensure_ascii=False).encode()).hexdigest()[:24]
        with central_db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM university_groups WHERE id=?',(key,)).fetchone():
                from services.security import limit
                limit('new-group-owner',owner,5,86400,connection=c)
                limit('new-group-total','all',100,86400,connection=c)
                c.execute('INSERT INTO university_groups VALUES(?,?,?,?,?,?,?,?)',(key,faculty,key,name,level,course,'excel',owner))
                c.execute('INSERT INTO university_group_programs VALUES(?,?)',(key,program.strip()))
    from database import central_setting,default_group
    pending=central_setting('study_choice:'+owner)=='1'
    if not member['admin'] and faculty not in ('ffl','fgp'):
        inherited=(owner_profile(owner) or {}).get('group_id')
        if not pending or faculty=='hist' or (faculty=='fgu' and key not in (default_group(),inherited)):abort(403)
    if key:
        if not isinstance(key,str) or len(key)>128:abort(400)
        group=group_record(key)
        if not group or group['faculty']!=faculty:abort(400)
    else:abort(400)
    initialize_group(key)
    with central_db() as c:
        c.execute('INSERT INTO university_profiles VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET faculty=excluded.faculty,group_id=excluded.group_id',(owner,faculty,key,utc_now()))
        c.execute('DELETE FROM settings WHERE key=?',('study_choice:'+owner,))
    if group['source']=='fgu':
        from services.timetable import start_sync
        start_sync(key)
    elif group['source'] in ('geo','hist'):
        from services.timetable import sync_schedule
        sync_schedule(key)
    return jsonify(ok=True,group=group)
