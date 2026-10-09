"""Synchronize selected study groups from their published timetable sources."""
import json,logging,threading,time
from datetime import date,datetime,timedelta,timezone
import requests
from database import get_db,get_setting,set_setting,utc_now,current_group,group_record,group_context,active_groups,central_db

_locks={};_guard=threading.Lock()
_queued=set();_attempts={}
SYNC_COOLDOWN=60
SYNC_MAX_AGE=1800
logger=logging.getLogger(__name__)

def requested_days(payload,first,last):
    """The source includes extra empty dates in future responses; keep our range."""
    if not isinstance(payload,list):raise ValueError('Invalid response')
    selected=[]
    for day in payload:
        if not isinstance(day,dict) or not isinstance(day.get('lessons'),list) or not isinstance(day.get('date'),str):
            raise ValueError('Invalid timetable day')
        stamp=date.fromisoformat(day['date'])
        if day['date']!=stamp.isoformat():raise ValueError('Invalid timetable date')
        if first<=stamp<=last:selected.append(day)
    if payload and not selected:raise ValueError('Source returned an unrelated date range')
    return selected

def sync_schedule(key=None):
    key=key or current_group();record=group_record(key)
    if not record or record['source'] not in ('fgu','geo','hist'):return True
    with _guard:lock=_locks.setdefault(key,threading.Lock())
    if not lock.acquire(blocking=False):return False
    try:
        with group_context(key):
            if record['source'] in ('geo','hist'):
                try:
                    from services.external_schedules import geo_data,hist_schedule
                    if record['source']=='geo':
                        days=geo_data()[1].get(record['source_id'],[])
                    else:
                        days=hist_schedule(record['source_id'])
                    if not days:raise ValueError('В источнике нет занятий для выбранной группы')
                    group=get_setting('group_id')
                    first=min(day['date'] for day in days)
                    last=max(day['date'] for day in days)
                    c=get_db()
                    try:
                        with c:
                            c.execute('DELETE FROM schedules WHERE group_id=? AND day BETWEEN ? AND ?',(group,first,last))
                            for day in days:
                                c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',(group,day['date'],json.dumps(day,ensure_ascii=False)))
                            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('sync_'+group,utc_now()))
                    finally:c.close()
                    set_setting('sync_error_'+group,'')
                    return True
                except Exception as error:
                    logger.warning('Timetable source %s failed: %s',record['source'],type(error).__name__)
                    set_setting('sync_error_'+get_setting('group_id'),'Не удалось обновить расписание. Сохранённые занятия доступны.')
                    return False
            group=record['source_id'];today=datetime.now(timezone(timedelta(hours=3))).date();start=today-timedelta(days=30);start-=timedelta(days=start.weekday());end=today+timedelta(days=90)
            monday=today-timedelta(days=today.weekday());ranges=[(monday,monday+timedelta(days=6)),(monday+timedelta(days=7),monday+timedelta(days=13))]
            ranges += [(start+timedelta(days=i),min(end,start+timedelta(days=i+6))) for i in range(0,(end-start).days+1,7)]
            failures=[]
            for first,last in dict.fromkeys(ranges):
                try:
                    response=requests.post('https://my.spa.msu.ru/api/web/timetable/group',json={'groupId':group,'dateStart':first.isoformat(),'dateEnd':last.isoformat()},timeout=20);response.raise_for_status();days=requested_days(response.json(),first,last)
                    c=get_db()
                    try:
                        with c:
                            c.execute('DELETE FROM schedules WHERE group_id=? AND day BETWEEN ? AND ?',(group,first.isoformat(),last.isoformat()))
                            for day in days:c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',(group,day['date'],json.dumps(day,ensure_ascii=False)))
                            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('sync_'+group,utc_now()))
                    finally:c.close()
                except Exception as error:
                    failures.append(type(error).__name__)
                    logger.warning('FGU timetable %s to %s failed: %s',first,last,type(error).__name__)
            set_setting('sync_error_'+group,'Часть расписания не удалось обновить. Сохранённые занятия доступны.' if failures else '')
            return not failures
    finally:lock.release()

def is_syncing(key=None):
    key=key or current_group()
    with _guard:
        lock=_locks.get(key)
        return key in _queued or bool(lock and lock.locked())

def start_sync(key=None,force=False):
    """Queue one fetch for the assigned group, including newly admitted members."""
    key=key or current_group();record=group_record(key)
    if not record or record['source'] not in ('fgu','geo','hist'):return False
    now=time.monotonic()
    with _guard:
        lock=_locks.get(key)
        if key in _queued or (lock and lock.locked()):return True
        if not force and now-_attempts.get(key,-SYNC_COOLDOWN)<SYNC_COOLDOWN:return False
        _queued.add(key);_attempts[key]=now
    def run():
        try:sync_schedule(key)
        finally:
            with _guard:_queued.discard(key)
    try:threading.Thread(target=run,daemon=True,name='GroupSync').start()
    except Exception:
        with _guard:_queued.discard(key)
        raise
    return True

def ensure_schedule(key=None,has_cache=False):
    key=key or current_group()
    with group_context(key):updated=get_setting('sync_'+get_setting('group_id'))
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(updated)).total_seconds()
        fresh=has_cache and age<SYNC_MAX_AGE
    except (ValueError,TypeError):fresh=False
    if not fresh:start_sync(key)
    return is_syncing(key)

def sync_all_schedules():
    ok=True
    from services.group_comparison import watched_groups
    for key in dict.fromkeys(active_groups()+watched_groups()):
        try:ok=sync_schedule(key) and ok
        except Exception:ok=False
    return ok
