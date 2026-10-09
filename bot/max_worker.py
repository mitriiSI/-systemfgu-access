"""Durable authenticated MAX webhooks and administrator announcements."""
import base64,hashlib,json,threading,time
from cryptography.fernet import Fernet
from config import DATA_DIR,get_public_url
from database import central_db,central_setting,central_set_setting
from services import max_platform as platform
from services.bot_context import messenger

def cipher():
    from config import SESSION_SECRET
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('MAX queue:'+SESSION_SECRET).encode()).digest()))

def normalize(update):
    kind=update.get('update_type')
    if kind in ('bot_started','bot_stopped'):
        user_id=platform.valid_user_id(update['user']['user_id'])
        stamp=update['timestamp']
        if type(stamp) is not int:raise ValueError('Invalid event timestamp')
        return {'type':kind,'user':user_id,'id':kind+':'+str(user_id)+':'+str(stamp),'text':'/start '+str(update.get('payload') or '')}
    if kind not in ('message_created','message_callback'):return None
    message=update.get('message') or {}
    if message.get('recipient',{}).get('chat_type')!='dialog':return None
    if kind=='message_created':
        sender=message.get('sender',{})
        if sender.get('is_bot'):return None
        user_id=platform.valid_user_id(sender['user_id']);mid=message.get('body',{}).get('mid')
        text=message.get('body',{}).get('text') or ''
        if not isinstance(mid,str) or not 1<=len(mid)<=256 or not isinstance(text,str) or len(text)>16000:raise ValueError('Invalid message')
        return {'type':kind,'user':user_id,'id':'message:'+mid,'mid':mid,'text':text}
    callback=update['callback'];user_id=platform.valid_user_id(callback['user']['user_id'])
    recipient=message.get('recipient',{}).get('user_id')
    if recipient is not None and recipient!=user_id:return None
    value=callback.get('payload') or '';ident=callback['callback_id']
    if not isinstance(ident,str) or not 1<=len(ident)<=256 or not isinstance(value,str) or len(value)>1024:raise ValueError('Invalid callback')
    return {'type':kind,'user':user_id,'id':'callback:'+ident,'callback':ident,'payload':value,'mid':message.get('body',{}).get('mid')}

def enqueue(update):
    item=normalize(update)
    if item is None:return
    encoded=cipher().encrypt(json.dumps(item,ensure_ascii=False).encode()).decode()
    with central_db() as c:
        c.execute("DELETE FROM max_events WHERE status IN ('done','unknown') AND created<?",(time.time()-7*86400,))
        c.execute('INSERT OR IGNORE INTO max_events(id,user_id,body,created) VALUES(?,?,?,?)',(item['id'],item['user'],encoded,time.time()))

def reply(user_id,text,markup=None,owner=None):
    return platform.send_telegram('sendMessage',{'text':text,'reply_markup':markup or {}},user_id=user_id,owner=owner)

def login_request(user_id,token):
    with central_db() as c:row=c.execute("SELECT * FROM max_logins WHERE token=? AND expires>? AND status='pending'",(token,time.time())).fetchone()
    if not row:return reply(user_id,'Запрос истёк. Начните вход заново.')
    with central_db() as c:binding=c.execute('SELECT owner FROM max_identities WHERE user_id=?',(user_id,)).fetchone()
    if binding and not platform.member_for_owner(binding['owner']):return reply(user_id,'Доступ к этому аккаунту отключён. Обратитесь к администратору.')
    result=reply(user_id,'Подтвердить вход на сайт '+get_public_url()+'?\nПодтверждайте, только если сами начали вход в своём браузере. Запрос действует 5 минут.',{'inline_keyboard':[[{'text':'Подтвердить вход','callback_data':'maxlogin:approve:'+token},{'text':'Отклонить','callback_data':'maxlogin:deny:'+token}]]})
    if not binding:link_prompt(user_id)
    return result

def link_prompt(user_id):
    return reply(user_id,'Уже пользуетесь Midiary в Telegram? Напишите сюда свой Telegram ID из команды /myid в Telegram. Привязку нужно подтвердить в Telegram; нового аккаунта не будет.\nЕсли аккаунта ещё нет, регистрация — по коду администратора.',{'inline_keyboard':[[{'text':'Регистрация','callback_data':'reg:start'}]]})

def confirm_login(item):
    action,_,token=item['payload'][9:].partition(':')
    if action not in ('approve','deny'):return
    member=platform.identity(item['user'])
    with central_db() as c:
        binding=c.execute('SELECT owner FROM max_identities WHERE user_id=?',(item['user'],)).fetchone()
        changed=0
        if not binding or member:changed=c.execute("UPDATE max_logins SET status=?,user_id=? WHERE token=? AND expires>? AND status='pending'",('approved' if action=='approve' else 'denied',item['user'],token,time.time())).rowcount
    text=('Вход подтверждён. Вернитесь в тот браузер, где начали вход.' if action=='approve' else 'Вход отклонён.') if changed else 'Запрос истёк или у аккаунта нет доступа.'
    platform.send_telegram('answerCallbackQuery',{'callback_query_id':item['callback'],'text':text},user_id=item['user'])
    if item.get('mid'):platform.send_telegram('editMessageText',{'message_id':item['mid'],'text':text},user_id=item['user'])

def broadcast_summary(job):
    with central_db() as c:
        counts=dict(c.execute('SELECT status,count(*) FROM max_broadcast_deliveries WHERE job=? GROUP BY status',(job,)))
    return 'Рассылка MAX #'+str(job)+'\nОтправлено: '+str(counts.get('sent',0))+'\nОжидают: '+str(counts.get('queued',0)+counts.get('sending',0))+'\nПропущено: '+str(counts.get('skipped',0))+'\nОшибки: '+str(counts.get('failed',0))+'\nНеопределённая доставка: '+str(counts.get('unknown',0))

def broadcast(item,member,text,status_only=False):
    owner=member['owner']
    if not member['admin']:return reply(item['user'],'Управление доступно администратору.',owner=owner)
    from bot.broadcast import initialize
    from services.announcements import queue,paired_summary
    initialize()
    if status_only:
        with central_db() as c:
            row=c.execute('SELECT id FROM max_broadcasts WHERE owner=? ORDER BY id DESC LIMIT 1',(owner,)).fetchone()
            tg_row=c.execute('SELECT id FROM broadcasts WHERE admin=? ORDER BY id DESC LIMIT 1',(member['tg'],)).fetchone()
        return reply(item['user'],paired_summary(tg_row['id'],row['id']) if row and tg_row else broadcast_summary(row['id']) if row else 'Рассылок пока нет. Команда: /broadcast Текст объявления',owner=owner)
    if not text or len(text.encode('utf-16-le'))//2>3600:return reply(item['user'],'Напиши: /broadcast Текст объявления\nДо 3600 символов. Сообщение получат активные участники в подключённых Telegram и MAX. Статус: /broadcast_status',owner=owner)
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');tg_job,job=queue(c,owner,'max',item['mid'],text)
    return reply(item['user'],'Объявление поставлено в очередь.\n'+paired_summary(tg_job,job)+'\nПроверить: /broadcast_status',owner=owner)

def process(item):
    user_id=item['user'];member=platform.identity(user_id)
    if item['type']=='bot_stopped':
        if member:central_set_setting('max_delivery_disabled:'+member['owner'],'1')
        return
    if item['type']=='bot_started' and member:central_set_setting('max_delivery_disabled:'+member['owner'],'0')
    if item['type']=='message_callback' and item['payload'].startswith('maxlogin:'):return confirm_login(item)
    text=item.get('text','');parts=text.split(maxsplit=1);command=parts[0].split('@')[0] if parts else '';arg=parts[1].strip() if len(parts)>1 else ''
    if command=='/myid':return reply(user_id,str(user_id),owner=member['owner'] if member else None)
    if command=='/link':return reply(user_id,platform.link_code(user_id,arg))
    if command=='/start' and arg.startswith('login_'):return login_request(user_id,arg[6:])
    if not member:
        from services.bot_registration import load
        if text.strip().isdigit() and not load('max',user_id):
            from services.max_account_link import request_link
            if not 0<int(text.strip())<2**63:return reply(user_id,'Проверьте Telegram ID командой /myid в Telegram.')
            return reply(user_id,request_link(user_id,int(text.strip())))
        if command=='/start' and not arg.startswith('register'):return link_prompt(user_id)
    if command in ('/broadcast','/broadcast_status'):
        if not member:return reply(user_id,'Сначала привяжите аккаунт Midiary командой /link и своим кодом.')
        return broadcast(item,member,arg,status_only=command=='/broadcast_status')
    # Admin privileges come from an existing owner binding, never a matching numeric MAX ID.
    canonical=member['tg'] if member and member['admin'] else -user_id
    context={'platform':'max','user_id':user_id,'canonical':canonical,'owner':member['owner'] if member else None}
    from bot.handlers import handle_command,handle_callback
    with messenger(context):
        if item['type']=='message_callback':
            if not item.get('mid'):return
            return handle_callback({'id':item['callback'],'from':{'id':canonical},'data':item['payload'],'message':{'chat':{'type':'private','id':canonical},'message_id':item['mid']}})
        try:return handle_command({'from':{'id':canonical},'chat':{'type':'private','id':canonical},'text':text,'message_id':item.get('mid','')})
        except (ValueError,KeyError):return reply(user_id,'Проверь команду: /help. ID и названия тем не должны повторяться.',owner=context['owner'])

def process_one():
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT * FROM max_events WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if not row:return False
        c.execute("UPDATE max_events SET status='sending' WHERE id=?",(row['id'],))
    state='done'
    try:process(json.loads(cipher().decrypt(row['body'].encode())))
    except Exception as error:
        # A command may have committed before its reply failed: do not replay it blindly.
        state='unknown';print('MAX update error: '+type(error).__name__,flush=True)
    with central_db() as c:c.execute('UPDATE max_events SET status=?,body=? WHERE id=?',(state,'',row['id']))
    return True

def deliver_broadcast():
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT d.*,b.owner,b.body FROM max_broadcast_deliveries d JOIN max_broadcasts b ON d.job=b.id WHERE d.status='queued' AND retry_at<=? ORDER BY job,user_id LIMIT 1",(time.time(),)).fetchone()
        if not row:return False
        c.execute("UPDATE max_broadcast_deliveries SET status='sending',attempts=attempts+1 WHERE job=? AND user_id=?",(row['job'],row['user_id']))
    member=platform.identity(row['user_id']);admin=platform.member_for_owner(row['owner']);state='skipped';retry=0
    if member and member['owner']==row['recipient_owner'] and admin and admin['admin'] and central_setting('privacy_broadcast_'+member['owner'],'1')=='1' and central_setting('max_delivery_disabled:'+member['owner'],'0')!='1':
        from services.i18n import translate,owner_language
        footer=translate('Отключить общие объявления: /unsubscribe',owner_language(member['owner']))
        try:
            platform.send_telegram('sendMessage',{'text':row['body']+'\n\n'+footer,'_midiary_user_content':True},user_id=row['user_id'],owner=member['owner']);state='sent'
        except platform.MaxAPIError as error:
            state='queued' if error.code==429 and row['attempts']<3 else 'failed';retry=time.time()+60*(row['attempts']+1)
        except Exception:state='unknown' # An HTTP timeout does not prove that no message was delivered.
    with central_db() as c:c.execute('UPDATE max_broadcast_deliveries SET status=?,retry_at=? WHERE job=? AND user_id=?',(state,retry,row['job'],row['user_id']))
    return True

def notify_complete():
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM max_broadcasts b WHERE notified=0 AND NOT EXISTS(SELECT 1 FROM max_broadcast_deliveries d WHERE d.job=b.id AND status IN ('queued','sending')) ORDER BY id LIMIT 1").fetchone()
        if not row:return
        c.execute('UPDATE max_broadcasts SET notified=1 WHERE id=?',(row['id'],))
    user_id=platform.user_for_owner(row['owner']);member=platform.member_for_owner(row['owner'])
    if user_id and member and member['admin']:reply(user_id,broadcast_summary(row['id']),owner=row['owner'])

def start_worker(stop):
    platform.initialize()
    if not platform.configured():return
    with central_db() as c:
        c.execute("UPDATE max_events SET status='unknown',body='' WHERE status='sending'")
        c.execute("UPDATE max_broadcast_deliveries SET status='unknown' WHERE status='sending'")
    def loop():
        while not stop.is_set():
            try:
                process_one();deliver_broadcast();notify_complete()
                with central_db() as c:pending=c.execute("SELECT count(*) FROM max_events WHERE status='queued'").fetchone()[0]
                path=DATA_DIR/'max-health.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps({'checked_at':time.time(),'pending':pending}),encoding='utf-8');temp.replace(path)
            except Exception as error:print('MAX worker error: '+type(error).__name__,flush=True)
            stop.wait(.5)
    threading.Thread(target=loop,daemon=True,name='MaxWebhookWorker').start()
