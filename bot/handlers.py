"""Telegram commands restored from the original diary application."""
import hashlib
import hmac
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from config import ADMIN_IDS as ADMINS, REMINDER_CHOICES, SESSION_SECRET, get_public_url as public_url
from database import central_connection as _get_db, central_setting as setting, central_set_setting as put_setting, utc_now as now
from services.telegram import tg_call
from services.timetable import sync_schedule,start_sync
from services.community import db as group_db
from database import get_setting as group_setting
from database import register_telegram,owner_profile,group_context,group_record,initialize_group,central_db

@contextmanager
def db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def confirm_browser(callback):
    data=callback.get('data','');action,_,token=data.partition(':');tg=callback['from']['id']
    if action not in ('login','deny'): return
    message=callback.get('message',{})
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg:return
    with db() as c:
        blocked=c.execute('SELECT active FROM members WHERE tg=?',(tg,)).fetchone()
        allowed=tg in ADMINS or not blocked or bool(blocked['active'])
        changed=0
        # Confirm identity only. Unknown users still need an invitation on the website.
        if allowed: changed=c.execute("UPDATE browser_logins SET status=?,tg=? WHERE token=? AND status='pending' AND expires>?",('approved' if action=='login' else 'denied',tg,token,int(time.time()))).rowcount
    text=('Вход подтверждён. Вернитесь в тот браузер, где начали вход.' if action=='login' else 'Вход отклонён.') if changed else 'Запрос истёк или у аккаунта нет доступа.'
    tg_call('answerCallbackQuery',callback_query_id=callback['id'],text=text[:200])
    tg_call('editMessageText',chat_id=tg,message_id=message['message_id'],text=text)

def bot_member(tg):
    from services.bot_context import current
    context=current.get()
    if context and context['platform']=='max':
        from services.max_platform import identity
        return identity(context['user_id'])
    if tg in ADMINS:
        return {'owner':'admin:'+str(tg), 'tg':tg, 'english':setting('english_'+str(tg))}
    with db() as c:
        row=c.execute('SELECT * FROM members WHERE tg=? AND active=1',(tg,)).fetchone()
    from services.privacy import blocked
    return dict(row) | {'owner':'member:'+row['code']} if row and not blocked('member:'+row['code']) else None

def reminder_menu(tg, message_id=None):
    user=bot_member(tg)
    if not user:
        tg_call('sendMessage',chat_id=tg,text='Сначала открой дневник через /start и введи ID от администратора. Затем отправь /notifications.')
        return
    with group_db() as c:
        pref=c.execute('SELECT minutes FROM reminder_prefs WHERE owner=?',(user['owner'],)).fetchone()
    from services.midiary import offsets
    minutes=pref[0] if pref else 0
    values=offsets(user['owner'],'telegram:lessons',[minutes] if minutes else [])
    text=('Напоминания о парах: '+(', '.join(str(v)+' мин.' for v in values) if values else 'выключены')+
          '\nВыбери время до начала пары. Время занятий — московское.\nЛичная характеристика преподавателя видна только тебе. Общая пометка администратора — всем.')
    keyboard=[]
    for i in range(0,len(REMINDER_CHOICES),2):
        keyboard.append([{'text':('✓ ' if n in values else '')+f'За {n} мин.', 'callback_data':f'remind:{n}'} for n in REMINDER_CHOICES[i:i+2]])
    keyboard.append([{'text':('✓ ' if not values else '')+'Выключить', 'callback_data':'remind:0'}])
    keyboard.append([{'text':'ДЗ на завтра','callback_data':'homework:menu'}])
    keyboard.append([{'text':'Куда присылать уведомления','callback_data':'channels:menu'}])
    data={'chat_id':tg,'text':text,'reply_markup':{'inline_keyboard':keyboard}}
    if message_id is not None: data['message_id']=message_id
    tg_call('editMessageText' if message_id is not None else 'sendMessage',**data)

def reminder_callback(callback):
    tg=callback['from']['id'];message=callback.get('message',{})
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg: return
    user=bot_member(tg)
    value=callback.get('data','').partition(':')[2]
    if value=='menu':
        tg_call('answerCallbackQuery',callback_query_id=callback['id'])
        user=bot_member(tg);profile=owner_profile(user['owner']) if user else None
        if profile and profile['group_id']:
            with group_context(profile['group_id']):reminder_menu(tg)
        else:tg_call('sendMessage',chat_id=tg,text='Сначала выберите факультет и группу на сайте.')
        return
    if not user or not value.isdigit() or int(value) not in (0,*REMINDER_CHOICES):
        tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Нет доступа или неверная настройка.')
        return
    from services.midiary import offsets,save_offsets,LESSON_OFFSETS
    with group_db() as c:old=c.execute('SELECT minutes FROM reminder_prefs WHERE owner=?',(user['owner'],)).fetchone()
    values=offsets(user['owner'],'telegram:lessons',[old[0]] if old and old[0] else [])
    minutes=int(value)
    if minutes==0:values=[]
    elif minutes in values:values.remove(minutes)
    else:values.append(minutes)
    save_offsets(user['owner'],'telegram:lessons',values,LESSON_OFFSETS)
    with group_db() as c:c.execute('INSERT OR REPLACE INTO reminder_prefs VALUES(?,?)',(user['owner'],max(values,default=0)))
    tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Настройки сохранены')
    reminder_menu(tg,message['message_id'])


def homework_menu(tg,message_id=None):
    user=bot_member(tg)
    if not user:return tg_call('sendMessage',chat_id=tg,text='Сначала привяжите аккаунт Midiary командой /link и своим кодом.')
    from services.homework_reminders import times,CHOICES
    selected=times(user['owner']);clock=lambda value:f'{value//60:02}:{value%60:02}'
    text='ДЗ на завтра: '+(', '.join(map(clock,selected)) if selected else 'выключены')+'\nТолько если для ваших завтрашних пар записано общее ДЗ. Время московское. Можно выбрать до 4 времён.\nСвоё время: /homework 19:30 22:00. Выключить: /homework off'
    keyboard=[[{'text':('✓ ' if value in selected else '')+clock(value),'callback_data':'homework:'+str(value)}] for value in sorted(set(CHOICES+selected))]
    keyboard.append([{'text':'Выключить','callback_data':'homework:off'}])
    data={'chat_id':tg,'text':text,'reply_markup':{'inline_keyboard':keyboard}}
    if message_id is not None:data['message_id']=message_id
    return tg_call('editMessageText' if message_id is not None else 'sendMessage',**data)

def homework_callback(callback):
    tg=callback['from']['id'];message=callback.get('message',{})
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg:return
    user=bot_member(tg)
    if not user:return tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Нет доступа')
    from services.homework_reminders import times,save_times
    value=callback.get('data','').partition(':')[2];selected=times(user['owner'])
    try:
        if value=='off':selected=[]
        elif value!='menu':
            if not value.isdigit() or not 0<=int(value)<1440:raise ValueError()
            minute=int(value)
            if minute in selected:selected.remove(minute)
            else:selected.append(minute)
        save_times(user['owner'],selected)
    except ValueError:return tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Можно выбрать до 4 времён.')
    tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Настройки сохранены')
    return homework_menu(tg,message['message_id'])

HELP='''/homework — время напоминаний о ДЗ на завтра
/register — регистрация по приглашению администратора
/invite КОЛИЧЕСТВО [ГРУППА] — код на заданное число регистраций (7 дней)
/allow TELEGRAM_ID [ГРУППА] — разрешить регистрацию без кода (7 дней)
/disallow TELEGRAM_ID — отозвать разрешение регистрации
/groupfor ID ГРУППА — назначить участнику другую группу
/subscription — мой доступ и будущая подписка
/subscriptionprice ЦЕНА — базовая цена в рублях (оплата пока отключена)
/discount ID ЦЕНА — персональная цена участника в рублях
/free ID [ДНИ] — бесплатный доступ; без срока, если дни не указаны
/subscriptionreset ID — убрать персональные условия
/link КОД — привязать уведомления Telegram и MAX
/site — текущий адрес дневника в браузере
/notifications — кнопки настройки напоминаний
/unsubscribe — отключить общие объявления
/subscribe — включить общие объявления
/add — используйте /invite и самостоятельную регистрацию
/rename ID Новое ФИО — исправить имя
/rename Старое ФИО | Новое ФИО — исправить по имени
/mycode СЕКРЕТНЫЙ_КОД — задать код входа администратора на сайт
/moderation ID on — включить подтверждение общих правок участника
/moderation ID off — отключить подтверждение
/broadcast Текст — объявление всем активным участникам
/broadcast_status — результат последней рассылки
/members — список участников
/revoke ID или имя — закрыть доступ
/reset ID или имя — отвязать мессенджеры и восстановить доступ
/group 1457 107пб — выбрать расписание
/sync — обновить расписание
/status — состояние загрузки расписания
/topic Название — создать тему литературы
/pending — изменения на подтверждение
/approve НОМЕР — подтвердить
/reject НОМЕР — отклонить
/myid — ID в этом мессенджере'''

def resolve_member(text):
    text=text.strip()
    if not text: return None,'Укажи ID или имя. Например: /revoke 827415 или /revoke Лобачева Элата Александровна'
    normalize=lambda s:' '.join(s.casefold().replace('ё','е').split())
    with db() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM members')]
    code=text.split()[0]
    exact=[r for r in rows if r['code']==code]
    if exact:return exact[0],''
    identity=[r for r in rows if str(r['tg'])==text]
    if identity:return identity[0],''
    query=normalize(text)
    matches=[r for r in rows if normalize(r['name'])==query]
    if not matches:
        tokens=query.split()
        matches=[r for r in rows if all(t in normalize(r['name']).split() for t in tokens)]
    if len(matches)==1:return matches[0],''
    if not matches:return None,'Участник не найден. Проверь ID или имя: /members'
    return None,'Найдено несколько участников. Укажи ID:\n'+'\n'.join(r['code']+' · '+r['name'] for r in matches[:10])

def _command(message):
    if message.get('chat',{}).get('type')!='private': return
    tg=message['from']['id'];text=message.get('text','');parts=text.split(maxsplit=1)
    if not parts:return
    cmd=parts[0].split('@')[0];arg=parts[1].strip() if len(parts)>1 else ''
    from services import bot_registration
    if cmd in ('/register','/registration') or (cmd=='/start' and arg.startswith('register')):return bot_registration.start(tg,arg.partition('_')[2] if cmd=='/start' else None)
    if bot_registration.message(tg,text):return
    reply=''
    if cmd=='/myid': reply=str(tg)
    elif cmd=='/start' and arg.startswith('login_'):
        token=arg[6:]
        with db() as c:
            valid=c.execute("SELECT token FROM browser_logins WHERE token=? AND status='pending' AND expires>?",(token,int(time.time()))).fetchone()
            blocked=c.execute('SELECT active FROM members WHERE tg=?',(tg,)).fetchone()
        allowed=tg in ADMINS or not blocked or bool(blocked['active'])
        if not valid: reply='Запрос истёк. Начните вход на сайте заново.'
        elif not allowed: reply='Доступ к этому аккаунту отключён. Обратитесь к администратору.'
        else:
            tg_call('sendMessage',chat_id=tg,text='Подтвердить вход на сайт '+public_url()+'?\nПодтверждайте, только если сами начали вход в своём браузере. Запрос действует 5 минут.',reply_markup={'inline_keyboard':[[{'text':'Подтвердить вход','callback_data':'login:'+token},{'text':'Отклонить','callback_data':'deny:'+token}]]});return
    elif cmd=='/start':
        tg_call('sendMessage',chat_id=tg,text='Откройте дневник. Если аккаунта ещё нет, нажмите «Регистрация» и введите приглашение администратора. Для привязки существующего аккаунта используйте /link КОД_ДОСТУПА.',reply_markup={'inline_keyboard':[[{'text':'Открыть расписание','web_app':{'url':public_url()}}],[{'text':'Регистрация','callback_data':'reg:start'}],[{'text':'Напоминания','callback_data':'remind:menu'}]]});return
    elif cmd in ('/register','/registration'):
        tg_call('sendMessage',chat_id=tg,text='Регистрация в Midiary доступна по одноразовому приглашению администратора. Коды общие для Telegram, MAX и сайта. Если аккаунт уже есть, используйте его личный код доступа.',reply_markup={'inline_keyboard':[[{'text':'Регистрация','callback_data':'reg:start'}],[{'text':'Открыть расписание','web_app':{'url':public_url()}}]]});return
    elif cmd=='/homework':
        user=bot_member(tg)
        if not user:return homework_menu(tg)
        if arg:
            from services.homework_reminders import save_times
            if arg=='off':values=[]
            else:
                clocks=arg.split()
                if len(clocks)>4 or any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',clock) for clock in clocks):return tg_call('sendMessage',chat_id=tg,text='Укажите время: /homework 19:30 22:00. Можно выбрать до 4 времён.')
                values=[int(clock[:2])*60+int(clock[3:]) for clock in clocks]
            save_times(user['owner'],values)
        return homework_menu(tg)
    elif cmd=='/site':
        url=public_url()
        if url:
            tg_call('sendMessage',chat_id=tg,text='Текущий адрес дневника в браузере:\n'+url,reply_markup={'inline_keyboard':[[{'text':'Открыть сайт','url':url}]]});return
        reply='Адрес ещё не получен. Попробуй через минуту.'
    elif cmd in ('/notifications','/reminders'):
        user=bot_member(tg);profile=owner_profile(user['owner']) if user else None
        if profile and profile['group_id']:
            with group_context(profile['group_id']):reminder_menu(tg)
        else:tg_call('sendMessage',chat_id=tg,text='Сначала выберите факультет и группу на сайте.')
        return
    elif cmd=='/link':
        with db() as c:
            c.execute('BEGIN IMMEDIATE');attempt=c.execute('SELECT * FROM attempts WHERE tg=?',(tg,)).fetchone()
            if attempt and attempt['until']>time.time() and attempt['count']>=5:
                reply='Слишком много попыток. Попробуйте через 15 минут.'
            else:
                c.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(tg,attempt['count']+1 if attempt and attempt['until']>time.time() else 1,int(time.time()+900)))
                row=c.execute('SELECT * FROM members WHERE code=? AND active=1',(arg,)).fetchone()
                occupied=c.execute('SELECT code FROM members WHERE tg=?',(tg,)).fetchone()
                if not row or (row['tg'] is not None and row['tg']!=tg) or (occupied and occupied['code']!=arg):reply='Код не найден или Telegram уже привязан.'
                else:
                    c.execute('UPDATE members SET tg=? WHERE code=?',(tg,arg));c.execute('DELETE FROM attempts WHERE tg=?',(tg,))
                    reply='Telegram подключён к уведомлениям Midiary.'
    elif cmd in ('/unsubscribe','/subscribe'):
        user=bot_member(tg)
        if not user:reply='Сначала привяжите аккаунт Midiary командой /link и своим кодом.'
        else:
            put_setting('privacy_broadcast_'+user['owner'],'1' if cmd=='/subscribe' else '0')
            reply='Общие объявления выключены. Напоминания о парах и дедлайнах сохраняются.' if cmd=='/unsubscribe' else 'Общие объявления включены. Отключить: /unsubscribe'
    elif cmd=='/subscription':
        user=bot_member(tg)
        if not user:reply='Сначала зарегистрируйтесь или войдите в дневник: /start.'
        else:
            from services.subscriptions import text as subscription_text
            reply=subscription_text(user['owner'])
    elif tg not in ADMINS: reply='Управление доступно администратору. Дневник: /start. Напоминания: /notifications'
    elif cmd=='/subscriptionprice':
        from services.subscriptions import set_base,rubles
        try:set_base('admin:'+str(tg),rubles(arg));reply='Базовая цена сохранена. ФГУ бесплатно; приём платежей пока отключён.'
        except ValueError as error:reply=str(error)
    elif cmd in ('/discount','/free','/subscriptionreset'):
        from services.subscriptions import set_override,rubles
        values=arg.rsplit(maxsplit=1) if cmd in ('/discount','/free') else [arg]
        target=values[0] if values else '';found,problem=resolve_member(target)
        if not found:reply=problem
        else:
            try:
                if cmd=='/subscriptionreset':set_override('admin:'+str(tg),found['code'],reset=True)
                elif cmd=='/discount':
                    if len(values)!=2:raise ValueError('Например: /discount TELEGRAM_ID 99.50')
                    set_override('admin:'+str(tg),found['code'],personal_price=rubles(values[1]))
                else:
                    until=None
                    if len(values)==2:
                        if not values[1].isdigit() or not 1<=int(values[1])<=36500:raise ValueError('Например: /free TELEGRAM_ID 30 или /free TELEGRAM_ID без срока.')
                        until=time.time()+int(values[1])*86400
                    set_override('admin:'+str(tg),found['code'],free=True,free_until=until)
                reply='Условия участника '+found['name']+' сохранены. Приём платежей пока отключён.'
            except ValueError as error:reply=str(error)
    elif cmd=='/invite':
        from services.admissions import create_invitation
        values=arg.split()
        if len(values)>2 or (values and not values[0].isascii()) or (values and not values[0].isdigit()):
            reply='Например: /invite 5 или /invite 5 1457. По умолчанию — одна регистрация в 107пб.'
        else:
            count=int(values[0]) if values else 1
            key=values[1] if len(values)>1 else 'fgu:1457'
            if ':' not in key:key='fgu:'+key
            try:reply='Код на '+str(count)+' регистраций (7 дней), группа '+(group_record(key) or {}).get('name',key)+': '+create_invitation('admin:'+str(tg),count=count,group_id=key)
            except ValueError as error:reply=str(error)
    elif cmd=='/allow':
        from services.admissions import allow_telegram
        values=arg.split()
        if not 1<=len(values)<=2:reply='Например: /allow 123456789 или /allow 123456789 1457.'
        else:
            key=values[1] if len(values)>1 else 'fgu:1457'
            if ':' not in key:key='fgu:'+key
            try:
                allowed=allow_telegram('admin:'+str(tg),values[0],group_id=key)
                reply='Регистрация разрешена Telegram ID '+str(allowed)+' на 7 дней. Участнику нужно отправить /register и подтвердить согласия. Группа: '+group_record(key)['name']+'.'
            except ValueError as error:reply=str(error)
    elif cmd=='/disallow':
        from services.admissions import revoke
        try:revoke('admin:'+str(tg),'telegram',arg);reply='Разрешение регистрации отозвано. Уже созданный аккаунт отключается командой /revoke.'
        except ValueError as error:reply=str(error)
    elif cmd=='/groupfor':
        from services.admissions import assign_member
        values=arg.rsplit(maxsplit=1)
        if len(values)!=2:reply='Например: /groupfor TELEGRAM_ID 1457. Можно указать ID аккаунта или имя участника.'
        else:
            found,problem=resolve_member(values[0]);key=values[1]
            if ':' not in key:key='fgu:'+key
            if not found:reply=problem
            else:
                try:
                    assign_member('admin:'+str(tg),found['code'],key);start_sync(key)
                    reply='Группа участника '+found['name']+': '+group_record(key)['name']+'.'
                except ValueError as error:reply=str(error)
    elif cmd in ('/help','/admin'): reply=HELP
    elif cmd in ('/broadcast', '/broadcast_status'):
        from bot.broadcast import handle
        handle(message, arg, status_only=cmd=='/broadcast_status');return
    elif cmd=='/mycode':
        if not re.fullmatch(r'[A-Za-z0-9_-]{12,64}',arg):
            reply='Задай код длиной 12–64 символа: латиница, цифры, - и _. Не используй свой Telegram ID.'
        else:
            with db() as c: exists=c.execute('SELECT code FROM members WHERE code=?',(arg,)).fetchone()
            if exists: reply='Этот код занят участником. Выбери другой.'
            else:
                put_setting('admin_code_'+str(tg),hmac.new(SESSION_SECRET.encode(),('admin-code:'+arg).encode(),hashlib.sha256).hexdigest())
                reply='Код входа администратора сохранён. Теперь его можно вводить на сайте.'
    elif cmd=='/moderation':
        target,mode=arg.rsplit(maxsplit=1)
        if mode not in ('on','off'): raise ValueError()
        found,problem=resolve_member(target)
        if not found: reply=problem
        else:
            put_setting('moderate_'+found['code'],'1' if mode=='on' else '0');reply='Подтверждение общих правок '+('включено' if mode=='on' else 'отключено')+'. ДЗ, файлы и личные записи публикуются без подтверждения.'
    elif cmd=='/rename':
        if '|' in arg:
            target,name=arg.split('|',1)
        else:
            parts=arg.split(maxsplit=1)
            target,name=parts if len(parts)==2 else ('','')
        name=' '.join(name.split())
        if not target.strip() or not name or len(name)>200:
            reply='Например: /rename 827415 Лобачева Злата Александровна. По имени: /rename Лобачева Элата Александровна | Лобачева Злата Александровна'
        else:
            found,problem=resolve_member(target)
            if not found:reply=problem
            else:
                with db() as c:c.execute('UPDATE members SET name=? WHERE code=?',(name,found['code']))
                reply='Имя исправлено: '+name+' · ID '+found['code']+('\nДоступ остаётся отключённым. Вернуть: /reset '+found['code'] if not found['active'] else '')
    elif cmd=='/add':
        reply='Создайте код командой /invite. Участник зарегистрируется сам и отдельно подтвердит условия и обработку данных. Для младше 18 лет создайте специальное приглашение в профиле сайта после подтверждения представителя.'
    elif cmd=='/members':
        with db() as c: reply='\n'.join(f"{r['code']} · {r['name']} · {'активен' if r['active'] else 'отключён'}" for r in c.execute('SELECT * FROM members')) or 'Пока нет участников'
    elif cmd in ('/revoke','/reset'):
        found,problem=resolve_member(arg)
        if not found:reply=problem
        else:
            with db() as c:
                c.execute('UPDATE members SET active=? WHERE code=?',(0 if cmd=='/revoke' else 1,found['code']))
                if cmd=='/reset': c.execute('UPDATE members SET tg=NULL WHERE code=?',(found['code'],))
                if cmd=='/reset':
                    c.execute('DELETE FROM max_identities WHERE owner=?',('member:'+found['code'],))
                    c.execute('DELETE FROM max_file_tickets WHERE owner=?',('member:'+found['code'],))
            reply=('Доступ отключён: ' if cmd=='/revoke' else 'Доступ восстановлен, Telegram и MAX отвязаны: ')+found['name']+' · ID '+found['code']
    elif cmd=='/group':
        raw=arg.split()[0] if arg else '';key='fgu:'+raw
        if not group_record(key):reply='Группа не найдена. Выберите группу в профиле сайта.'
        else:
            initialize_group(key)
            with central_db() as c:c.execute("UPDATE university_profiles SET faculty='fgu',group_id=? WHERE owner=?",(key,'admin:'+str(tg)))
            start_sync(key);reply='Ваша группа изменена. Обновление запущено.'
    elif cmd=='/status':
        group=group_setting('group_id')
        with group_db() as c: count=c.execute('SELECT count(*) FROM schedules WHERE group_id=?',(group,)).fetchone()[0]
        reply='Группа: '+group_setting('group_name')+'; ID ФГУ: '+group+'\nСохранено дней: '+str(count)+'\nПоследняя загрузка: '+group_setting('sync_'+group,'ещё не было')+'\n'+group_setting('sync_error_'+group,'')
    elif cmd=='/sync':
        profile=owner_profile('admin:'+str(tg));start_sync(profile['group_id'] if profile else None);reply='Обновление вашей группы запущено.'
    elif cmd=='/topic':
        if not arg or len(arg)>200: raise ValueError()
        with group_db() as c: c.execute('INSERT INTO topics(title) VALUES(?)',(arg,))
        reply='Тема создана'
    elif cmd=='/pending':
        with group_db() as c: reply='\n\n'.join(f"#{r['id']} {r['kind']} · {r['item']}\n{r['author']}\n{r['body']}" for r in c.execute("SELECT * FROM proposals WHERE status='pending'")) or 'Нет изменений на подтверждение'
    elif cmd in ('/approve','/reject'):
        with group_db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute("SELECT * FROM proposals WHERE id=? AND status='pending'",(int(arg),)).fetchone()
            if not r: reply='Заявка не найдена или уже обработана'
            else:
                if cmd=='/approve':
                    c.execute('INSERT INTO revisions(kind,item,body,author,updated) VALUES(?,?,?,?,?)',(r['kind'],r['item'],r['body'],r['author'],now()))
                    c.execute('INSERT OR REPLACE INTO content VALUES(?,?,?,?,?)',(r['kind'],r['item'],r['body'],r['author'],now()))
                c.execute('UPDATE proposals SET status=? WHERE id=?',('approved' if cmd=='/approve' else 'rejected',r['id']))
                reply='Подтверждено' if cmd=='/approve' else 'Отклонено'
    else: reply=HELP
    for start in range(0,len(reply),3800): tg_call('sendMessage',chat_id=tg,text=reply[start:start+3800])


def handle_command(message):
    return command(message)


def handle_callback(callback):
    if callback.get('data','').startswith('reg:'):
        from services.bot_registration import callback as register_callback
        return register_callback(callback)
    if callback.get('data','').startswith('maxlink:'):
        from services.max_account_link import confirm
        from services.bot_context import current
        if current.get() and current.get()['platform']=='max':return
        return confirm(callback)
    if callback.get('data','').startswith('channels:'):
        from bot.notification_settings import callback as channel_callback
        return channel_callback(callback)
    if callback.get('data','').startswith('homework:'):return homework_callback(callback)
    if callback.get('data', '').startswith('remind:'):
        user=bot_member(callback['from']['id']);profile=owner_profile(user['owner']) if user else None
        if profile and profile['group_id']:
            with group_context(profile['group_id']):return reminder_callback(callback)
        return tg_call('answerCallbackQuery',callback_query_id=callback['id'],text='Сначала выберите группу на сайте.')
    return confirm_browser(callback)


def command(message):
    user=bot_member(message.get('from',{}).get('id'));profile=owner_profile(user['owner']) if user else None
    with group_context(profile['group_id'] if profile else None):return _command(message)
