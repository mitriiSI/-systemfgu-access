"""Account-bound schedule comparisons, private notes and shared-class markers."""
import hashlib
import json
import re
import time
from datetime import date,datetime,timedelta
from flask import Blueprint,abort,jsonify,request
from config import PRIMARY_ADMIN_ID,MOSCOW_TZ
from database import (central_db,central_setting,central_set_setting,group_context,group_record,
                      group_path,initialize_group,owner_profile,get_setting)
from services import community
from services.schedule_presentation import subject_label
from services.teachers import subject_overrides,with_teachers,teacher_list

comparison_bp=Blueprint('group_comparison',__name__)
TARGET='fgu:1454'
OFFSETS=(0,5,10,15,30,60,120)
CHANNELS=('telegram','max','website')
COMMON_NOTICE='Общая пара с 107))'

def primary(owner):return owner=='admin:'+str(PRIMARY_ADMIN_ID)

def initialize():
    with central_db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS group_comparison_access(
      id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL UNIQUE,
      target_group TEXT NOT NULL,created REAL NOT NULL,peer_owner TEXT);
    CREATE TABLE IF NOT EXISTS group_comparison_messages(
      recipient TEXT PRIMARY KEY,body TEXT NOT NULL,expires REAL NOT NULL);
    ''')
    with central_db() as c:
        if 'peer_owner' not in {row['name'] for row in c.execute('PRAGMA table_info(group_comparison_access)')}:
            c.execute('ALTER TABLE group_comparison_access ADD COLUMN peer_owner TEXT')

def grant_member(owner,target_group):
    """Server-side provisioning; never infer access from a display name."""
    if not isinstance(owner,str) or not owner.startswith('member:'):raise ValueError('Unknown member')
    target=group_record(target_group)
    if not target or target['faculty']!='fgu':raise ValueError('Unknown group')
    with central_db() as c:
        row=c.execute('SELECT active FROM members WHERE code=?',(owner[7:],)).fetchone()
        if not row or not row['active']:raise ValueError('Unknown member')
        c.execute('INSERT INTO group_comparison_access(owner,target_group,created) VALUES(?,?,?) '
                  'ON CONFLICT(owner) DO UPDATE SET target_group=excluded.target_group',
                  (owner,target_group,time.time()))

def active_account(owner):
    if primary(owner):return True
    if not isinstance(owner,str) or not owner.startswith('member:'):return None
    with central_db() as c:
        row=c.execute('SELECT active FROM members WHERE code=?',(owner[7:],)).fetchone()
    if not row or not row['active']:return False
    from services.privacy import blocked
    return not blocked(owner)

def access_record(owner):
    with central_db() as c:row=c.execute('SELECT target_group,peer_owner FROM group_comparison_access WHERE owner=?',(owner,)).fetchone()
    return dict(row) if row else None

def target_for(owner):
    access=access_record(owner)
    if not access:return TARGET if primary(owner) else None
    if not active_account(owner):return None
    peer=access['peer_owner']
    if not peer:return access['target_group']
    reverse=access_record(peer)
    if not active_account(peer) or not reverse or reverse['peer_owner']!=owner:return None
    return (owner_profile(peer) or {}).get('group_id')

def peer_for(owner):
    access=access_record(owner)
    return access['peer_owner'] if access and target_for(owner) else None

def bind_pair(member_owner):
    """Only the provisioned member can be paired with the primary account."""
    if not isinstance(member_owner,str) or not member_owner.startswith('member:') or not access_record(member_owner) or not active_account(member_owner):
        raise ValueError('Unknown comparison member')
    admin_owner='admin:'+str(PRIMARY_ADMIN_ID)
    member_group=(owner_profile(member_owner) or {}).get('group_id')
    admin_group=(owner_profile(admin_owner) or {}).get('group_id')
    if not member_group or not admin_group:raise ValueError('Учебная группа ещё не выбрана.')
    with central_db() as c:
        c.execute('UPDATE group_comparison_access SET peer_owner=?,target_group=? WHERE owner=?',
                  (admin_owner,admin_group,member_owner))
        c.execute('INSERT INTO group_comparison_access(owner,target_group,created,peer_owner) VALUES(?,?,?,?) '
                  'ON CONFLICT(owner) DO UPDATE SET target_group=excluded.target_group,peer_owner=excluded.peer_owner',
                  (admin_owner,member_group,time.time(),member_owner))

def allowed(owner):return primary(owner) or bool(target_for(owner))
def integrated(owner):return bool(not primary(owner) and target_for(owner))
def pref_key(owner):return 'midiary_offsets:'+owner+':group-comparison'
def preferences(owner):
    default={'label':'','notify_common':False,'notify_other':False,'offsets':[15],
             'channels':dict.fromkeys(CHANNELS,True)}
    try:
        value=json.loads(central_setting(pref_key(owner),'{}'))
        return validate(default|value) if isinstance(value,dict) else default
    except (ValueError,TypeError):return default

def validate(value):
    if not isinstance(value,dict) or set(value)!={'label','notify_common','notify_other','offsets','channels'}:
        raise ValueError('Проверьте настройки уведомлений.')
    label=value['label']
    if not isinstance(label,str) or len(label)>60 or re.search(r'[\x00-\x1f\x7f]',label):
        raise ValueError('Подпись должна быть короче 61 символа и без переносов строк.')
    if any(type(value[key]) is not bool for key in ('notify_common','notify_other')):
        raise ValueError('Проверьте выбор занятий.')
    offsets=value['offsets'];channels=value['channels']
    if not isinstance(offsets,list) or len(offsets)>len(OFFSETS) or any(type(v) is not int or v not in OFFSETS for v in offsets):
        raise ValueError('Выберите время напоминания из списка.')
    if not isinstance(channels,dict) or set(channels)!=set(CHANNELS) or any(type(v) is not bool for v in channels.values()):
        raise ValueError('Проверьте каналы уведомлений.')
    if (value['notify_common'] or value['notify_other']) and (not offsets or not any(channels.values())):
        raise ValueError('Выберите время напоминания и хотя бы один канал.')
    return {**value,'label':label.strip(),'offsets':sorted(set(offsets)),'channels':dict(channels)}

def save_preferences(owner,value):
    if not allowed(owner):raise PermissionError('Private feature')
    if integrated(owner):
        if not isinstance(value,dict) or set(value)!={'label'}:raise ValueError('Уведомления настраиваются в основном разделе профиля.')
        value=preferences(owner)|value
    value=validate(value);central_set_setting(pref_key(owner),json.dumps(value,ensure_ascii=False));return value

def watched_groups():
    owner='admin:'+str(PRIMARY_ADMIN_ID)
    with central_db() as c:owners=[owner]+[r[0] for r in c.execute('SELECT owner FROM group_comparison_access')]
    targets={target_for(account) for account in owners if (owner_profile(account) or {}).get('group_id')}
    result=[]
    for target in sorted(targets-{None}):
        if not group_record(target):continue
        if not group_path(target).is_file():initialize_group(target)
        result.append(target)
    return result

def active_note(owner,at=None):
    with central_db() as c:row=c.execute('SELECT body,expires FROM group_comparison_messages WHERE recipient=? AND expires>?',
                                      (owner,time.time() if at is None else at)).fetchone()
    return dict(row) if row else None

def message_recipients():
    with central_db() as c:rows=[dict(r) for r in c.execute("SELECT a.id,a.owner,m.name FROM group_comparison_access a "
          "JOIN members m ON a.owner='member:'||m.code WHERE m.active=1 ORDER BY a.id")]
    return [{'id':r['id'],'name':r['name'],'note':active_note(r['owner'])} for r in rows if allowed(r['owner'])]

def save_message(editor,value):
    if not primary(editor):raise PermissionError('Private feature')
    if not isinstance(value,dict) or set(value)!={'recipient','body','minutes'}:raise ValueError('Проверьте сообщение и срок показа.')
    ident,body,minutes=(value[key] for key in ('recipient','body','minutes'))
    if type(ident) is not int or type(minutes) is not int or not 1<=minutes<=10080:
        raise ValueError('Срок показа — от 1 минуты до 7 дней.')
    if not isinstance(body,str) or len(body)>800 or re.search(r'[\x00-\x08\x0b-\x1f\x7f]',body):
        raise ValueError('Сообщение — до 800 символов.')
    with central_db() as c:row=c.execute('SELECT owner FROM group_comparison_access WHERE id=?',(ident,)).fetchone()
    if not row or not allowed(row['owner']):raise ValueError('Получатель недоступен.')
    recipient=row['owner'];body=body.strip()
    with central_db() as c:
        if body:c.execute('INSERT OR REPLACE INTO group_comparison_messages VALUES(?,?,?)',(recipient,body,time.time()+minutes*60))
        else:c.execute('DELETE FROM group_comparison_messages WHERE recipient=?',(recipient,))
    return active_note(recipient)

@comparison_bp.route('/api/admin/group-comparison/messages',methods=['GET','POST'])
def messages():
    from routes.auth import get_personal_owner
    owner=get_personal_owner()
    if not primary(owner):abort(403)
    if request.method=='GET':return jsonify(recipients=message_recipients())
    try:return jsonify(note=save_message(owner,request.get_json(silent=True)))
    except ValueError as error:return jsonify(error=str(error)),400

def record(day,lesson,period):
    # Whitelist schedule metadata. No material IDs, links, homework or identities.
    return {'date':day,'number':lesson.get('number',0),
            'title':subject_label(period.get('_diary_title') or period.get('disciplineFullName') or 'Пара'),
            'start':str(period.get('timeStart') or ''),'end':str(period.get('timeEnd') or ''),
            'room':str(period.get('classroom') or ''),'teachers':teacher_list(period.get('teachers') or period.get('teacher') or period.get('teachersNameFull') or period.get('teachersName')),
            'type':str(period.get('typeStr') or '')}

def normalize(value):return re.sub(r'[\s.\-–]+','',str(value).casefold().replace('ё','е'))
def shared(a,b):
    if (a['date'],a['start'],a['end'],normalize(a['title']))!=(b['date'],b['start'],b['end'],normalize(b['title'])):return False
    room_a,room_b=normalize(a['room']),normalize(b['room'])
    if room_a and room_b and room_a!=room_b:return False
    teachers_a={normalize(t) for t in a['teachers']};teachers_b={normalize(t) for t in b['teachers']}
    if teachers_a and teachers_b and not teachers_a.intersection(teachers_b):return False
    return bool((room_a and room_a==room_b) or teachers_a.intersection(teachers_b))

def entries(raw,wanted):
    return [record(day['date'],lesson,period) for day in raw if day['date'] in wanted
            for lesson in day.get('lessons',[]) for period in lesson.get('periods',[])]

def personal_entries(owner,wanted,raw=None):
    result=entries(community.filtered_days(owner,raw),wanted)
    for event in community.events(owner,min(wanted),max(wanted)):
        if event['date'] in wanted and event.get('type')=='lesson':
            result.append(record(event['date'],{},dict(_diary_title=event['title'],timeStart=event['start'],
                timeEnd=event.get('end',''),classroom=event.get('room',''),
                teachers=event.get('teachers') or event.get('teacher'),typeStr='Пара')))
    return result

def timetable_data(owner,first,last,now,refresh=False):
    if not allowed(owner):raise PermissionError('Private feature')
    profile=owner_profile(owner) or {};own_group=profile.get('group_id');target_id=target_for(owner);target=group_record(target_id) if target_id else None
    if not own_group or not target:raise ValueError('Учебная группа ещё не выбрана.')
    if not group_path(target_id).is_file():initialize_group(target_id)
    today=now.date().isoformat();wanted={today}|{(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)}
    peer=peer_for(owner)
    if (access_record(owner) or {}).get('peer_owner') and not peer:raise ValueError('Связанное расписание сейчас недоступно.')
    with group_context(own_group):
        own=personal_entries(owner,wanted)
    with group_context(target_id):
        raw=community.official_days();overrides=subject_overrides()
        # A reciprocal account binding shares schedule metadata only. Without a
        # binding, retain the legacy public timetable; never guess a group member.
        public=personal_entries(peer,wanted,raw) if peer else [record(day['date'],lesson,with_teachers(period,overrides))
                for day in raw if day['date'] in wanted for lesson in day.get('lessons',[]) for period in lesson.get('periods',[])]
        updated=get_setting('sync_'+target['source_id'])
    unique={}
    for lesson in public:
        key=(lesson['date'],lesson['start'],lesson['end'],normalize(lesson['title']),normalize(lesson['room']),tuple(sorted(map(normalize,lesson['teachers']))))
        lesson['common']=any(shared(lesson,mine) for mine in own)
        if key in unique:unique[key]['common']|=lesson['common']
        else:unique[key]=lesson
    public=sorted(unique.values(),key=lambda l:(l['date'],l['start'],l['title'],l['room']))
    daily=[lesson for lesson in public if lesson['date']==today];clock=now.strftime('%H:%M')
    current=[lesson for lesson in daily if lesson['start']<=clock<(lesson['end'] or lesson['start'])]
    upcoming=next((lesson for lesson in daily if lesson['start']>clock),None)
    syncing=False
    if refresh:
        from services.timetable import ensure_schedule
        syncing=ensure_schedule(target_id,has_cache=bool(raw))
    return {'group':{'id':target_id,'name':target['name']},'now':now.isoformat(),'today':today,
            'integrated_notifications':integrated(owner),'can_message':primary(owner),
            'note':active_note(owner),'offset_choices':list(OFFSETS),
            'preferences':preferences(owner),'updated':updated,'syncing':syncing,'has_cache':bool(raw),
            'current':current,'next':upcoming,'today_common':[l for l in daily if l['common']],
            'today_has_lessons':bool(daily),
            'days':[{'date':(first+timedelta(days=i)).isoformat(),'lessons':[l for l in public if l['date']==(first+timedelta(days=i)).isoformat()]} for i in range((last-first).days+1)]}

def snapshot(owner,selected,week=False,at=None,refresh=False):
    now=at or datetime.now(MOSCOW_TZ);first=date.fromisoformat(selected)
    if week:first-=timedelta(days=first.weekday())
    return timetable_data(owner,first,first+timedelta(days=6 if week else 0),now,refresh)

def candidates(owner,now):
    # Granted members use their normal reminders, never a second reminder stream.
    if not primary(owner):return []
    prefs=preferences(owner)
    if not (prefs['notify_common'] or prefs['notify_other']):return []
    payload=timetable_data(owner,now.date(),now.date()+timedelta(days=1),now)
    result=[]
    for day in payload['days']:
        for lesson in day['lessons']:
            if not prefs['notify_common' if lesson['common'] else 'notify_other']:continue
            try:begins=datetime.fromisoformat(lesson['date']+'T'+lesson['start']).replace(tzinfo=MOSCOW_TZ)
            except ValueError:continue
            for minutes in prefs['offsets']:
                due=begins-timedelta(minutes=minutes);expires=due+timedelta(minutes=3)
                if not due<=now<expires:continue
                identity=json.dumps([payload['group']['id'],lesson['date'],lesson['title'],lesson['start'],lesson['end'],lesson['room'],minutes],ensure_ascii=False)
                key='group-comparison:'+hashlib.sha256(identity.encode()).hexdigest()
                heading='У '+prefs['label']+' пара:' if prefs['label'] else 'Пара:'
                text=f'{heading} {lesson["title"]}.\n{lesson["start"]}–{lesson["end"]} · '+(lesson['room'] or 'Аудитория не указана')
                if lesson['common']:text+='\nУ вас общая пара.'
                result.append({'key':key,'title':'Общая пара' if lesson['common'] else 'Пара',
                               'body':text,'expires':expires.timestamp(),'date':lesson['date'],'channels':prefs['channels']})
    return result

def shared_marker(owner,now):
    """Build once per reminder pass; return a pure per-lesson lookup."""
    if not integrated(owner):return lambda lesson:''
    payload=timetable_data(owner,now.date(),now.date()+timedelta(days=1),now)
    common=[lesson for day in payload['days'] for lesson in day['lessons'] if lesson['common']]
    return lambda lesson:COMMON_NOTICE if any(shared(lesson,other) for other in common) else ''

@comparison_bp.route('/api/group-comparison',methods=['GET','POST'])
@comparison_bp.route('/api/admin/group-comparison',methods=['GET','POST'])
def comparison():
    from routes.auth import get_personal_owner
    owner=get_personal_owner()
    if not allowed(owner):abort(403)
    if request.method=='POST':
        try:return jsonify(preferences=save_preferences(owner,request.get_json(silent=True)))
        except ValueError as error:return jsonify(error=str(error)),400
    selected=request.args.get('date',datetime.now(MOSCOW_TZ).date().isoformat());week=request.args.get('week','0')
    try:
        parsed=date.fromisoformat(selected)
        if parsed.isoformat()!=selected or week not in ('0','1') or abs((parsed-datetime.now(MOSCOW_TZ).date()).days)>366:
            raise ValueError('Укажите дату в пределах года и режим день или неделя.')
        return jsonify(snapshot(owner,selected,week=='1',refresh=True))
    except ValueError as error:return jsonify(error=str(error)),400
