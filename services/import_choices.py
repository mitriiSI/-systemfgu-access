"""Personal choices among alternatives already saved from a timetable file."""
import json
from collections import defaultdict
from database import current_faculty, get_db, get_setting, set_setting

DAYS=('Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье')
NONE='__none'


def key(owner):return 'midiary_import_choices:'+owner


def catalogue(owner):
    choices=defaultdict(set);subgroups=defaultdict(set)
    if current_faculty() in ('fgp','ffl'):
        c=get_db()
        try:
            for row in c.execute('SELECT body FROM custom_lessons WHERE active=1 AND owner=? AND group_id=?',(owner,get_setting('group_id'))):
                data=json.loads(row['body'])
                if not data.get('_schedule_import'):continue
                if data.get('choice'):choices[data['choice']].add(data['title'])
                if data.get('group'):subgroups[data['title']].add(data['group'])
        finally:c.close()
    try:saved=json.loads(get_setting(key(owner),'{}'))
    except ValueError:saved={}
    if not isinstance(saved,dict):saved={}
    selected={section:saved.get(section,{}) if isinstance(saved.get(section),dict) else {} for section in ('choices','subgroups')}
    groups=[]
    for ident,options in sorted(choices.items()):
        if len(options)<2:continue
        parts=ident.split(':')
        label='Какой язык вы изучаете' if ident=='primary-language' else (DAYS[int(parts[1])]+', '+parts[2]+' пара — предмет по выбору' if len(parts)>2 and parts[1].isdigit() and int(parts[1])<7 else 'Предмет по выбору')
        groups.append({'id':ident,'label':label,'options':sorted(options)})
    branches=[{'id':title,'label':title+' — моя подгруппа','options':sorted(options)} for title,options in sorted(subgroups.items()) if len(options)>1]
    active=lambda title:all(title not in row['options'] or selected['choices'].get(row['id'])==title for row in groups)
    unresolved=[row['label'] for section,rows in (('choices',groups),('subgroups',branches)) for row in rows
                if (section=='choices' or active(row['id'])) and selected[section].get(row['id']) not in [NONE,*row['options']]]
    return {'choices':groups,'subgroups':branches,'selection':selected,'unresolved':unresolved,'available':bool(groups or branches)}


def visible(event,catalog):
    if not event.get('_schedule_import'):return True
    for row in catalog['choices']:
        if event.get('choice')==row['id'] and catalog['selection']['choices'].get(row['id'])!=event['title']:return False
    for row in catalog['subgroups']:
        if event['title']==row['id'] and event.get('group') and catalog['selection']['subgroups'].get(row['id'])!=event['group']:return False
    return True


def save(owner,body):
    catalog=catalogue(owner)
    if not isinstance(body,dict):raise ValueError('Проверьте выбранные варианты.')
    selection={}
    for section in ('choices','subgroups'):
        values=body.get(section,{})
        allowed={row['id']:row['options'] for row in catalog[section]}
        if not isinstance(values,dict) or any(ident not in allowed or value not in ['',NONE,*allowed[ident]] for ident,value in values.items()):
            raise ValueError('Варианты расписания изменились. Откройте выбор заново.')
        selection[section]={ident:value for ident,value in values.items() if value}
    set_setting(key(owner),json.dumps(selection,ensure_ascii=False))
    return catalogue(owner)
