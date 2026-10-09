"""Bounded spreadsheet parsing and previewed, atomic group timetable imports."""
import io,json,re,zipfile,hashlib,secrets,time
from datetime import datetime,date,timedelta,time as clock
from flask import Blueprint,request,jsonify,abort,current_app
from database import get_db,get_setting,current_faculty,group_record,central_db,utc_now
from routes.auth import get_personal_owner,get_current_member
from services.community import db

imports_bp=Blueprint('imports',__name__)

@imports_bp.route('/api/schedule/import/choices',methods=['GET','POST'])
def personal_import_choices():
    if current_faculty() not in ('fgp','ffl'):abort(400)
    from services.import_choices import catalogue,save
    if request.method=='GET':return jsonify(catalogue(get_personal_owner()))
    try:return jsonify(save(get_personal_owner(),request.get_json(silent=True)))
    except ValueError as error:return jsonify(error=str(error)),400

from services.spreadsheet_schedules import ALIASES,plain,normal,workbook_rows,parse_date,parse_time,preview

@imports_bp.post('/api/schedule/import/preview')
def import_preview():
    if group_record()['source']!='excel':return jsonify(error='Для ФГУ расписание загружается из «Мой ФГУ». Дополнительную пару можно добавить вручную.'),400
    file=request.files.get('file')
    if not file:abort(400)
    try:
        options=current_app.json.loads(request.form.get('options','{}'))
        if not isinstance(options,dict):abort(400)
        from services.bell_times import for_group
        options['bell_times']=for_group(group_record())
        from services.table_schedules import preview_table,MAX_FILE
        filename=file.filename or ''
        content=file.read(MAX_FILE+1)
        from services.parser_sandbox import parse_timetable
        if filename.lower().endswith(('.xlsx','.xls')):
            result=parse_timetable(content,filename,options,group_record()['name'])
            result['format']='excel';result['templates']=[]
            known=set()
            for entry in result['rows']:
                entry['weekday']=date.fromisoformat(entry['date']).weekday()
                entry.setdefault('group','');entry.setdefault('week','')
                ident=hashlib.sha256(json.dumps({key:value for key,value in entry.items() if key!='date'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
                entry['template_id']=ident
                if ident not in known:
                    known.add(ident);result['templates'].append(entry.copy())
        else:
            result=parse_timetable(content,filename,options,group_record()['name'])
    except ValueError as error:return jsonify(error=str(error)),400
    if not result['errors']:
        token=secrets.token_urlsafe(24)
        with db() as c:
            c.execute('DELETE FROM schedule_imports WHERE expires<? AND committed=0',(time.time(),))
            c.execute('INSERT INTO schedule_imports VALUES(?,?,?,?,?,?,0,0)',(token,get_personal_owner(),time.time(),time.time()+1800,json.dumps(result['rows'],ensure_ascii=False),(file.filename or 'Расписание')[:200]))
        result['token']=token
    return jsonify(result)

def reviewed_entries(entries,edits,personal=False):
    if not isinstance(edits,dict) or len(edits)>6000:raise ValueError('Некорректные исправления расписания.')
    known={entry.get('template_id','') for entry in entries}
    if any(key not in known for key in edits):raise ValueError('Предпросмотр изменился. Повторите распознавание.')
    output=[]
    for entry in entries:
        correction=edits.get(entry.get('template_id',''),{})
        if not isinstance(correction,dict) or type(correction.get('enabled',True)) is not bool:raise ValueError('Проверьте выбранные занятия.')
        if not correction.get('enabled',True):continue
        value=entry.copy()
        for key,limit in (('title',300),('teacher',200),('room',120),('group',80),('type',80)):
            if key in correction:
                if not isinstance(correction[key],str) or len(correction[key].strip())>limit:raise ValueError('Слишком длинное название, преподаватель, аудитория или подгруппа.')
                value[key]=correction[key].strip()
        if not value['title']:raise ValueError('Укажите предмет для каждого выбранного занятия.')
        value['start']=parse_time(correction.get('start',value['start']))
        value['end']=parse_time(correction.get('end',value['end']))
        if value['end']<=value['start']:raise ValueError('Окончание занятия должно быть позже начала.')
        output.append(value)
    if not output:raise ValueError('Выберите хотя бы одно занятие.')
    if personal:
        choices={};subgroups={}
        for entry in output:
            if entry.get('choice'):choices.setdefault(entry['choice'],set()).add(entry['title'])
            if entry.get('group'):subgroups.setdefault(entry['title'],set()).add(entry['group'])
        if any(len(values)>1 for values in choices.values()):
            raise ValueError('Выберите один предмет в каждой строке с вариантами расписания.')
        if any(len(values)>1 for values in subgroups.values()):
            raise ValueError('Выберите свою подгруппу для личного расписания.')
    return output

@imports_bp.post('/api/schedule/import/commit')
def import_commit():
    b=request.get_json()
    if not isinstance(b,dict) or type(b.get('replace',False)) is not bool:abort(400)
    if not isinstance(b.get('token'),str) or not 1<=len(b['token'])<=128:abort(400)
    if group_record()['source']!='excel':abort(400)
    visibility=b.get('visibility','personal' if current_faculty() in ('ffl','fgp') else 'group')
    if visibility not in ('personal','group'):abort(400)
    if visibility=='group' and not get_current_member()['admin']:abort(403)
    owner=get_personal_owner()
    with db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM schedule_imports WHERE id=? AND owner=?',(b.get('token'),get_personal_owner())).fetchone()
        if not row or row['expires']<time.time():return jsonify(error='Предпросмотр истёк. Загрузите файл ещё раз.'),409
        if row['committed']:return jsonify(ok=True,added=row['added'],visibility=visibility)
        try:entries=reviewed_entries(json.loads(row['payload']),b.get('edits',{}),personal=visibility=='personal')
        except (ValueError,TypeError,AttributeError) as error:return jsonify(error=str(error)),400
        group=get_setting('group_id');days={};teachers=set();added=0;before={}
        if visibility=='personal':
            dates={entry['date'] for entry in entries}
            if b.get('replace'):
                for item in c.execute('SELECT id,body FROM custom_lessons WHERE owner=? AND group_id=? AND active=1',(owner,group)).fetchall():
                    data=json.loads(item['body'])
                    if data.get('_schedule_import') and data.get('date') in dates:
                        before[item['id']]=data;c.execute('UPDATE custom_lessons SET active=0 WHERE id=?',(item['id'],))
            for entry in entries:
                ident='import-'+hashlib.sha256(json.dumps([owner,group,{key:value for key,value in entry.items() if key not in ('template_id','page','week','weekday')}],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                existing=c.execute('SELECT active FROM custom_lessons WHERE id=?',(ident,)).fetchone()
                if existing and existing['active']:continue
                data={key:entry.get(key,'') for key in ('date','number','title','start','end','teacher','room','type','group')}
                data.update(choice=entry.get('choice',''),template_id=entry.get('template_id',''))
                data.update(group_id=group,recurrence='once',_schedule_import=row['id'],lesson_type=data['type'],type='lesson')
                c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body,active=1',(ident,owner,group,json.dumps(data,ensure_ascii=False)))
                added+=1
                if entry['teacher']:teachers.add(entry['teacher'])
            c.execute('INSERT INTO revisions(kind,item,body,author,updated) VALUES(?,?,?,?,?)',('schedule_import',row['id'],json.dumps(before,ensure_ascii=False),owner,utc_now()))
            c.execute('UPDATE schedule_imports SET committed=1,added=? WHERE id=?',(added,row['id']))
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('personal_import:'+owner,utc_now()))
        else:
            added,before,teachers=commit_shared(c,entries,group,b,row['id'],owner)
    with central_db() as c:
        for teacher in teachers:c.execute('INSERT OR IGNORE INTO faculty_teachers VALUES(?,?,?,?,?)',(current_faculty(),teacher,'','','Файл расписания'))
    return jsonify(ok=True,added=added,visibility=visibility)

def commit_shared(c,entries,group,options,token,owner):
        days={};teachers=set();added=0;before={}
        for entry in entries:
            day=entry['date']
            if day not in days:
                old=c.execute('SELECT body FROM schedules WHERE group_id=? AND day=?',(group,day)).fetchone();before[day]=old[0] if old else None
                days[day]={'date':day,'lessons':[]} if options.get('replace') or not old else json.loads(old[0])
            ident=hashlib.sha256(json.dumps(entry,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if any(p.get('_import_id')==ident for lesson in days[day]['lessons'] for p in lesson.get('periods',[])):continue
            period={'_import_id':ident,'disciplineFullName':entry['title'],'timeStart':entry['start'],'timeEnd':entry['end'],'teachersNameFull':entry['teacher'],'classroom':entry['room'],'groups':entry.get('group',''),'typeStr':entry['type']}
            days[day]['lessons'].append({'number':entry['number'],'periods':[period]});added+=1
            if entry['teacher']:teachers.add(entry['teacher'])
        for day,data in days.items():
            data['lessons'].sort(key=lambda l:l['periods'][0]['timeStart']);c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',(group,day,json.dumps(data,ensure_ascii=False)))
        c.execute('INSERT INTO revisions(kind,item,body,author,updated) VALUES(?,?,?,?,?)',('schedule_import',token,json.dumps(before,ensure_ascii=False),owner,utc_now()))
        c.execute('UPDATE schedule_imports SET committed=1,added=? WHERE id=?',(added,token))
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('sync_'+group,utc_now()))
        return added,before,teachers
