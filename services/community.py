"""Personal timetable overlays and shared teacher reviews, independent of upstream sync."""
import copy
import hashlib
import json
from contextlib import contextmanager
from datetime import date, timedelta
from database import get_db, get_setting,central_db,current_faculty
from services.teachers import subject_overrides,with_teachers
from services.schedule_presentation import geography_label,subject_label

@contextmanager
def db():
    c=get_db()
    try:
        with c:yield c
    finally:c.close()

def initialize():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS hidden_lessons(owner TEXT,group_id TEXT,lesson_id TEXT,created TEXT,PRIMARY KEY(owner,group_id,lesson_id));
        CREATE TABLE IF NOT EXISTS custom_lessons(id TEXT PRIMARY KEY,owner TEXT,group_id TEXT,body TEXT,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS teacher_reviews(id TEXT PRIMARY KEY,teacher TEXT NOT NULL,owner TEXT NOT NULL,author TEXT NOT NULL,
          clarity INTEGER NOT NULL,knowledge INTEGER NOT NULL,communication INTEGER NOT NULL,recommend INTEGER NOT NULL,
          comment TEXT NOT NULL,public_author INTEGER NOT NULL,updated TEXT NOT NULL,UNIQUE(teacher,owner));
        CREATE INDEX IF NOT EXISTS custom_lessons_owner ON custom_lessons(group_id,owner,active);
        CREATE INDEX IF NOT EXISTS teacher_reviews_teacher ON teacher_reviews(teacher);
        ''')

def normalized(value):return ' '.join(str(value or '').lower().replace('ё','е').split())

def event_data(value):
    try:
        data=json.loads(value)
        if not isinstance(data,dict):return None
        date.fromisoformat(data['date'])
        if not isinstance(data.get('start'),str) or not isinstance(data.get('title'),str):return None
        return data
    except (ValueError,TypeError,KeyError):return None

def lesson_id(day,lesson,period,legacy=False):
    # Room, teacher and time corrections do not resurrect a hidden occurrence.
    parts=[day,str(lesson.get('number','')),normalized(period.get('disciplineFullName')),normalized(period.get('groups'))]
    if not legacy and not period.get('groups') and period.get('_diary_branch'):parts.append(period['_diary_branch'])
    return 'official:'+hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()

def is_mfk_placeholder(day,period):
    title=normalized(period.get('disciplineFullName'))
    return current_faculty()=='fgu' and date.fromisoformat(day).weekday()==2 and ('межфакультет' in title or title in ('мфк','межфакультетские курсы'))

def hidden_ids(owner,group=None):
    with db() as c:return {r[0] for r in c.execute('SELECT lesson_id FROM hidden_lessons WHERE owner=? AND group_id=?',(owner,group or get_setting('group_id')))}

def official_days():
    with db() as c:
        days=[json.loads(r[0]) for r in c.execute('SELECT body FROM schedules WHERE group_id=? ORDER BY day',(get_setting('group_id'),))]
    from services.subgroups import annotate
    return annotate(days)

def filtered_days(owner,days=None):
    source=official_days()
    hidden=hidden_ids(owner);result=copy.deepcopy(source if days is None else days);overrides=subject_overrides()
    from services.subgroups import describe,annotate,selected_choices
    # Reminders may pass a single day; detect branches against the entire cache.
    info=describe(source or result);choices=selected_choices(owner,info);annotate(result,info)
    from services.lesson_times import for_owner,rooms_for_owner
    time_corrections=for_owner(owner)
    room_corrections=rooms_for_owner(owner)
    for day in result:
        for lesson in day.get('lessons',[]):
            kept=[]
            for period in lesson.get('periods',[]):
                ident=lesson_id(day['date'],lesson,period)
                if ident in hidden or lesson_id(day['date'],lesson,period,legacy=True) in hidden or is_mfk_placeholder(day['date'],period):continue
                selected=choices.get(normalized(period.get('disciplineFullName')))
                if selected and period.get('_diary_branch') and period['_diary_branch']!=selected:continue
                period.update(with_teachers(period,overrides));period['teachersNameFull']=period['teacher']
                period['_diary_id']=ident
                if current_faculty()=='geo':
                    label,room=geography_label(period.get('_diary_title') or period.get('disciplineFullName'),period.get('classroom'))
                    period['_diary_title']=label
                    period['classroom']=room
                else:
                    period['_diary_title']=subject_label(period.get('disciplineFullName'))
                if ident in room_corrections:
                    period['classroom']=room_corrections[ident]
                    period['_room_override']=True
                if ident in time_corrections:
                    period['timeStart'],period['timeEnd']=time_corrections[ident]
                    period['_time_override']=True
                kept.append(period)
            lesson['periods']=kept
        day['lessons']=[lesson for lesson in day.get('lessons',[]) if lesson['periods']]
    return result

def events(owner,start,end,admin=False,include_hidden=False):
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    hidden=set() if include_hidden else hidden_ids(owner)
    output=[];group=get_setting('group_id');overrides=subject_overrides()
    with db() as c:
        legacy=list(c.execute("SELECT item,body FROM content WHERE kind='schedule_event'"))
        custom=list(c.execute("SELECT * FROM custom_lessons WHERE group_id=? AND active=1 AND owner IN (?, '*')",(group,owner)))
    for row in legacy:
        data=event_data(row['body'])
        if data is None:continue
        data=with_teachers(data,overrides)
        if data.get('group_id')!=group or data.get('deleted'):continue
        day=data['date']
        ident='event:'+row['item']+':'+day
        if first<=date.fromisoformat(day)<=last and ident not in hidden:
            output.append(dict(data,id=row['item'],occurrence_id=ident,can_delete=admin or data.get('creator')==owner,source='shared',recurrence='once'))
    for row in custom:
        data=event_data(row['body'])
        if data is None:continue
        data=with_teachers(data,overrides)
        begins=date.fromisoformat(data['date'])
        if data.get('recurrence')=='weekly':
            current=max(first,begins);current+=timedelta(days=(begins.weekday()-current.weekday())%7)
            dates=[]
            while current<=last:dates.append(current);current+=timedelta(days=7)
        else:dates=[begins] if first<=begins<=last else []
        for current in dates:
            ident='event:'+row['id']+':'+current.isoformat()
            if ident in hidden:continue
            output.append(dict(data,id=row['id'],series_id=row['id'],date=current.isoformat(),occurrence_id=ident,
                can_delete=row['owner']==owner or (row['owner']=='*' and admin),source='custom',visibility='group' if row['owner']=='*' else 'personal'))
    from services.lesson_times import for_owner,rooms_for_owner
    time_corrections=for_owner(owner)
    room_corrections=rooms_for_owner(owner)
    for event in output:
        event.pop('creator',None)
        if event['occurrence_id'] in time_corrections:
            event['start'],event['end']=time_corrections[event['occurrence_id']]
            event['_time_override']=True
        if event['occurrence_id'] in room_corrections:
            event['room']=room_corrections[event['occurrence_id']]
            event['_room_override']=True
    from services.import_choices import catalogue,visible
    choices=catalogue(owner)
    return sorted((event for event in output if include_hidden or visible(event,choices)),key=lambda e:(e['date'],e['start'],e['id']))

def teacher_names(owner):
    names=set();overrides=subject_overrides()
    for day in official_days():
        for lesson in day.get('lessons',[]):
            for period in lesson.get('periods',[]):
                names.update(with_teachers(period,overrides)['teachers'])
    if current_faculty()!='fgu':
        with central_db() as c:
            for row in c.execute('SELECT name FROM faculty_teachers WHERE faculty=?',(current_faculty(),)):names.add(row[0])
            for row in c.execute('SELECT DISTINCT teacher FROM faculty_reviews WHERE faculty=?',(current_faculty(),)):names.add(row[0])
    with db() as c:
        rows=list(c.execute("SELECT body FROM custom_lessons WHERE active=1 AND owner IN (?, '*') AND group_id=?",(owner,get_setting('group_id'))))
        rows+=list(c.execute("SELECT body FROM content WHERE kind='schedule_event'"))
    for row in rows:
        data=event_data(row[0])
        if data is None:continue
        if not data.get('deleted') and data.get('group_id',get_setting('group_id'))==get_setting('group_id'):
            names.update(with_teachers(data,overrides)['teachers'])
    return sorted(names,key=normalized)

initialize()
