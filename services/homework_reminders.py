"""One daily homework summary per chosen time, shared by all account channels."""
import hashlib,json
from datetime import datetime,timedelta
from urllib.parse import urlencode
from database import central_setting,central_set_setting,get_db,get_setting
from services.community import db,filtered_days,events

CHOICES=[18*60,20*60,22*60]
def settings_key(owner):return 'midiary_offsets:'+owner+':homework-times'
def times(owner):
    try:values=json.loads(central_setting(settings_key(owner),'[]'))
    except (ValueError,TypeError):return []
    return sorted(set(values)) if isinstance(values,list) and len(values)<=4 and all(type(v) is int and 0<=v<1440 for v in values) else []
def save_times(owner,values):
    if not isinstance(values,list) or len(values)>4 or any(type(v) is not int or not 0<=v<1440 for v in values):raise ValueError('Invalid homework reminder times')
    values=sorted(set(values));central_set_setting(settings_key(owner),json.dumps(values));return values

def tomorrow_homework(owner,member,now):
    date=(now+timedelta(days=1)).date().isoformat();group=get_setting('group_id');name=get_setting('group_name')
    with db() as c:
        raw=[json.loads(row[0]) for row in c.execute('SELECT body FROM schedules WHERE group_id=? AND day=?',(group,date))]
        # Content contains accepted edits; pending edits live in proposals.
        homework={row['item']:row['body'] for row in c.execute("SELECT item,body FROM content WHERE kind='homework'")}
    visible={}
    for day in filtered_days(owner,raw):
        for lesson in day.get('lessons',[]):
            for period in lesson.get('periods',[]):
                title=str(period.get('disciplineFullName') or 'Занятие').strip();marker=period.get('groups') or period.get('_diary_branch') or ''
                key='|'.join(map(str,(name,date,lesson.get('number'),title,marker)))
                if key not in homework and not period.get('groups'):
                    legacy='|'.join(map(str,(name,date,lesson.get('number'),title,'')))
                    if legacy in homework:homework[key]=homework[legacy]
                visible[key]=(period.get('timeStart') or '',title)
    for event in events(owner,date,date):
        visible['|'.join((name,date,'extra',str(event['id'])))]=(event.get('start') or '',event['title'])
    return date,[(title,homework[key]) for key,(clock,title) in sorted(visible.items(),key=lambda row:(row[1][0],row[1][1])) if homework.get(key,'').strip()]

def candidates(owner,member,now):
    slots=[]
    for value in times(owner):
        begins=now.replace(hour=value//60,minute=value%60,second=0,microsecond=0)
        if begins<=now<begins+timedelta(minutes=3):slots.append((value,begins))
    if not slots:return []
    date,items=tomorrow_homework(owner,member,now)
    if not items:return []
    body='\n\n'.join(title+'\n'+text.strip()[:320]+('…' if len(text.strip())>320 else '') for title,text in items[:6])
    if len(items)>6:body+='\n\nОстальные задания — в дневнике.'
    body=body.encode('utf-16-le')[:6000].decode('utf-16-le',errors='ignore')
    title='ДЗ на завтра · '+datetime.fromisoformat(date).strftime('%d.%m')
    result=[]
    for value,begins in slots:
        key='homework:'+json.dumps([get_setting('group_id'),date,value],ensure_ascii=False)
        payload={'title':title,'body':body,'tag':'midiary-hw-'+hashlib.sha256(key.encode()).hexdigest()[:24],'url':'/?'+urlencode({'view':'day','date':date})}
        result.append((key,payload,(begins+timedelta(minutes=3)).timestamp()))
    return result
