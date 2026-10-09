import json

import time

from datetime import datetime, timedelta

from config import ADMIN_IDS, MOSCOW_TZ, get_public_url

from database import get_db, get_setting, set_setting

from services.delivery import send_reliable_message

from services.telegram import tg_call

from services.timetable import sync_schedule,sync_all_schedules
from database import group_members,group_admins,active_groups,group_context,central_setting

from bot.handlers import handle_command, handle_callback



def check_reminders(at=None):
    """Use the same owner IDs as bot/web preferences; delivery owns durable retries."""
    import math
    now = at or datetime.now(MOSCOW_TZ)
    group = get_setting('group_id')
    from services.max_platform import user_for_owner
    admins = group_admins()
    with get_db() as conn:
        prefs = {r['owner']: r['minutes'] for r in conn.execute('SELECT * FROM reminder_prefs')}
        users = {('member:' + r['code']): dict(r)|{'max_id':user_for_owner('member:'+r['code'])} for r in group_members() if (r['tg'] is not None or user_for_owner('member:'+r['code'])) and (r['tg'] is None or int(r['tg']) not in admins)}
        for tg in admins:
            users['admin:' + str(tg)] = {'tg': tg, 'english': central_setting('english_' + str(tg)),'max_id':user_for_owner('admin:'+str(tg))}
        rows = list(conn.execute('SELECT body FROM schedules WHERE group_id=? AND day BETWEEN ? AND ?',
                    (group, now.date().isoformat(), (now + timedelta(days=1)).date().isoformat())))
        events = list(conn.execute("SELECT item,body FROM content WHERE kind='schedule_event'"))
        deadlines = list(conn.execute('SELECT d.*,s.owner,s.minutes FROM deadlines d JOIN deadline_subs s ON d.item=s.item WHERE d.group_name=?', (get_setting('group_name'),)))
    from services import community
    errors = 0
    def starts(day,clock):
        value=datetime.fromisoformat(day+'T'+clock)
        return value.replace(tzinfo=MOSCOW_TZ) if value.tzinfo is None else value.astimezone(MOSCOW_TZ)
    def candidates_for(owner):
        nonlocal errors
        candidates=[];raw=[]
        from services.group_comparison import shared_marker,record
        try:marker=shared_marker(owner,now)
        except Exception as error:
            errors+=1;_error_details('shared-class-marker',error);marker=lambda lesson:''
        for row in rows:
            try:raw.append(json.loads(row['body']))
            except (ValueError,TypeError):errors+=1
        for day in community.filtered_days(owner,raw):
            for lesson in day.get('lessons',[]):
                for period in lesson.get('periods',[]):
                    try:
                        begins=starts(day['date'],period['timeStart']);title=period.get('disciplineFullName') or 'Пара'
                        key=json.dumps([group,day['date'],lesson.get('number'),title],ensure_ascii=False)
                        if period.get('_diary_branch'):key+=':branch:'+period['_diary_branch']
                        candidates.append((key,begins,title,period.get('classroom') or 'Не указана',
                                           marker(record(day['date'],lesson,period))))
                    except (ValueError,TypeError,KeyError):errors+=1
        for event in community.events(owner,now.date().isoformat(),(now+timedelta(days=1)).date().isoformat()):
            try:
                begins=starts(event['date'],event['start'])
                from services.teachers import teacher_list
                metadata={'date':event['date'],'start':event['start'],'end':event.get('end',''),
                          'title':event['title'],'room':event.get('room',''),
                          'teachers':teacher_list(event.get('teachers') or event.get('teacher'))}
                candidates.append(('event:'+json.dumps([event['id'],begins.isoformat()]),begins,event['title'],
                                   event.get('room') or 'Не указана',marker(metadata) if event.get('type')=='lesson' else ''))
            except (ValueError,TypeError,KeyError):errors+=1
        return candidates

    attempted = 0
    def deliver(owner, key, text,channels=('telegram','max')):
        nonlocal attempted, errors
        payload = {'chat_id': users[owner]['tg'], 'text': text}
        if get_public_url():
            payload['reply_markup'] = {'inline_keyboard': [[{'text': 'Открыть расписание', 'web_app': {'url': get_public_url()}}]]}
        for channel,recipient in [('telegram',users[owner].get('tg')),('max',users[owner].get('max_id'))]:
            if recipient is None or channel not in channels:continue
            try:
                if channel=='telegram':send_reliable_message(owner, key, payload, now)
                else:send_reliable_message(owner,key,dict(payload,chat_id=recipient),now,channel='max')
                attempted += 1
            except Exception as error:
                errors += 1
                _error_details('reminder-delivery', error)

    for owner, user in users.items():
        from services.midiary import offsets
        legacy=prefs.get(owner,0);values=offsets(owner,'telegram:lessons',[legacy] if legacy else [])
        if not values:continue
        for key, begins, title, room, notice in candidates_for(owner):
            # Catch up after downtime while the lesson is still in the future.
            for minutes in values:
                if not begins-timedelta(minutes=minutes)<=now<begins-timedelta(minutes=minutes)+timedelta(minutes=3):continue
                remaining = max(1, math.ceil((begins-now).total_seconds()/60))
                heading=f'Через {remaining} мин. — {title}' if now<begins else 'Начало пары — '+title
                deliver(owner, key+':offset:'+str(minutes), heading+f'\nНачало: {begins:%H:%M} (МСК)\nАудитория: {room}'+
                        ('\n'+notice if notice else ''))
    for row in deadlines:
        if row['owner'] not in users:
            continue
        try:
            due = datetime.fromisoformat(row['due'])
            if due.tzinfo is None:
                raise ValueError('Deadline needs timezone')
            from services.midiary import offsets
            for minutes in offsets(row['owner'],'deadline:'+row['item'],[row['minutes']] if row['minutes'] else []):
                if not due-timedelta(minutes=minutes)<=now<due-timedelta(minutes=minutes)+timedelta(minutes=3):continue
                key = 'deadline:' + json.dumps([row['item'], row['due'],minutes], ensure_ascii=False)
                deliver(row['owner'], key, f"Дедлайн ДЗ: {row['title']}\nСдать до {due.astimezone(MOSCOW_TZ):%d.%m.%Y · %H:%M} (МСК)")
        except (ValueError, TypeError):
            errors += 1
    from services.homework_reminders import candidates as homework_candidates
    for owner,user in users.items():
        for key,payload,expires in homework_candidates(owner,user,now):
            deliver(owner,key,payload['title']+'\n\n'+payload['body'])
    from services.group_comparison import candidates as comparison_candidates
    for owner in users:
        try:
            for item in comparison_candidates(owner,now):
                deliver(owner,item['key'],item['title']+'\n'+item['body'],
                        channels=[channel for channel,enabled in item['channels'].items() if enabled])
        except Exception as error:
            errors+=1
            _error_details('comparison-reminders',error)
    return {'enabled_lesson_reminders': sum(owner in users for owner in prefs), 'deadline_subscriptions': sum(row['owner'] in users for row in deadlines), 'delivery_checks': attempted, 'errors': errors}



import os
import sqlite3
import threading
import traceback
from contextlib import contextmanager
from config import DATA_DIR
from database import get_db as _get_db


@contextmanager
def get_db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _error_details(stage, error):
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    if status is None:
        status = getattr(error, 'code', None)
    details = {'stage': stage, 'type': type(error).__name__, 'at': time.time()}
    if isinstance(status, int):
        details['http_status'] = status
    if getattr(error, 'method', None):
        details['telegram_method'] = error.method
        details['description'] = error.description
    frames = traceback.extract_tb(error.__traceback__)
    if frames:
        details['location'] = os.path.basename(frames[-1].filename) + ':' + str(frames[-1].lineno)
    # Do not log exception text or URLs: Telegram URLs contain the bot token.
    print('Bot error: ' + json.dumps(details), flush=True)
    return details


def _expired_callback(update, details):
    if 'callback_query' not in update or details.get('http_status') != 400:
        return False
    description = details.get('description', '').lower()
    method = details.get('telegram_method')
    if method == 'answerCallbackQuery':
        return any(text in description for text in ('query is too old', 'query id is invalid', 'query_id_invalid'))
    if method in ('editMessageText', 'editMessageReplyMarkup'):
        return any(text in description for text in ('message to edit not found', "message can't be edited"))
    return False


def _write_health(health):
    path = DATA_DIR / 'bot-health.json'
    temporary = path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(health), encoding='utf-8')
        temporary.replace(path)
    except OSError as error:
        _error_details('health-file', error)


def _schedule_loop(stop):
    while not stop.is_set():
        delay = 900
        try:
            if sync_all_schedules() is False:
                delay = 60
        except Exception as error:
            _error_details('schedule', error)
            delay = 60
        stop.wait(delay)


def _reminder_loop(stop):
    while not stop.is_set():
        try:
            result={}
            for key in active_groups():
                with group_context(key):part=check_reminders()
                for name,value in part.items():result[name]=result.get(name,0)+value
            path = DATA_DIR / "reminder-health.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(dict(result, checked_at=time.time())), encoding="utf-8")
            temporary.replace(path)
        except Exception as error:
            _error_details('reminders', error)
        stop.wait(15)


def poll_once(offset, health):
    updates = tg_call('getUpdates', offset=offset, timeout=20,
                      allowed_updates=['message', 'callback_query'])
    health['poll_ok_at'] = time.time()
    health.pop('last_error',None)
    health['phase'] = 'processing'
    _write_health(health)
    for update in updates:
        if update['update_id'] < offset:
            continue
        try:
            if 'callback_query' in update:
                handle_callback(update['callback_query'])
            if 'message' in update:
                try:
                    handle_command(update['message'])
                except (ValueError, sqlite3.IntegrityError):
                    message = update['message']
                    if message.get('chat', {}).get('type') == 'private':
                        tg_call('sendMessage', chat_id=message['chat']['id'],
                                text='Проверь команду: /help. ID и названия тем не должны повторяться.')
        except Exception as error:
            health['last_error'] = _error_details('handle-update', error)
            _write_health(health)
            # A blocked/deactivated recipient must not stall other users forever.
            if health['last_error'].get('http_status') != 403 and not _expired_callback(update, health['last_error']):
                raise
        offset = update['update_id'] + 1
        set_setting('bot_offset', str(offset))
        health['processed_updates'] = health.get('processed_updates', 0) + 1
    health['phase'] = 'polling'
    _write_health(health)
    return offset


def start_bot_worker(stop_event=None):
    stop = stop_event if stop_event is not None else threading.Event()
    from bot.broadcast import start_worker
    start_worker(stop)
    from services.webpush import start_worker as start_web_push
    start_web_push(stop)
    from services.privacy import start_worker as start_privacy
    start_privacy(stop)
    from services.support import start_worker as start_support
    start_support(stop)
    from services.channel_bridge import start_worker as start_channels
    start_channels(stop)
    try:
        from bot.max_worker import start_worker as start_max
        start_max(stop)
    except Exception as error:
        print('MAX startup error: '+type(error).__name__,flush=True)
    health = {'version': 1, 'started_at': time.time(), 'phase': 'starting', 'processed_updates': 0}
    _write_health(health)
    threading.Thread(target=_schedule_loop, args=(stop,), daemon=True, name='ScheduleWorker').start()
    threading.Thread(target=_reminder_loop, args=(stop,), daemon=True, name='ReminderWorker').start()
    print('Telegram polling worker started independently of schedule updates.', flush=True)
    while not stop.is_set():
        try:
            offset = int(get_setting('bot_offset', '0'))
            poll_once(offset, health)
        except Exception as error:
            health['last_error'] = _error_details('poll-loop', error)
            health['phase'] = 'retrying'
            _write_health(health)
            stop.wait(5)
