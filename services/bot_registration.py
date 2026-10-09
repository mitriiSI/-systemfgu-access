"""Invitation registration in authenticated private bot conversations."""
import base64,hashlib,json,secrets,time
from cryptography.fernet import Fernet
from config import SESSION_SECRET,ADMIN_IDS,get_public_url
from database import central_db,utc_now,central_set_setting

def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('Midiary registration:'+SESSION_SECRET).encode()).digest()))
def initialize():
    with central_db() as c:c.execute('CREATE TABLE IF NOT EXISTS bot_registrations(platform TEXT,user_id INTEGER,body TEXT NOT NULL,expires REAL NOT NULL,PRIMARY KEY(platform,user_id))')
def purge():
    initialize()
    with central_db() as c:c.execute('DELETE FROM bot_registrations WHERE expires<?',(time.time(),))
def context(tg):
    from services.bot_context import current
    value=current.get()
    return ('max',value['user_id']) if value and value['platform']=='max' else ('telegram',tg)
def load(platform,user):
    purge()
    with central_db() as c:row=c.execute('SELECT body FROM bot_registrations WHERE platform=? AND user_id=?',(platform,user)).fetchone()
    return json.loads(cipher().decrypt(row[0].encode())) if row else None
def save(platform,user,value):
    initialize()
    with central_db() as c:c.execute('INSERT OR REPLACE INTO bot_registrations VALUES(?,?,?,?)',(platform,user,cipher().encrypt(json.dumps(value,ensure_ascii=False).encode()).decode(),time.time()+900))
def clear(platform,user):
    with central_db() as c:c.execute('DELETE FROM bot_registrations WHERE platform=? AND user_id=?',(platform,user))
def send(tg,text,buttons=(),language='ru'):
    from services.telegram import tg_call
    from services.i18n import translate_payload
    values=translate_payload({'text':text,'reply_markup':{'inline_keyboard':list(buttons)}},language)
    return tg_call('sendMessage',chat_id=tg,**values,_midiary_user_content=True)
def existing(platform,user):
    if platform=='max':
        from services.max_platform import identity
        return identity(user)
    if user in ADMIN_IDS:return {'owner':'admin:'+str(user),'admin':True}
    with central_db() as c:row=c.execute('SELECT code,active FROM members WHERE tg=?',(user,)).fetchone()
    return {'owner':'member:'+row[0],'active':row[1]} if row else None
def start(tg,language=None):
    platform,user=context(tg)
    if existing(platform,user):return send(tg,'У вас уже есть аккаунт. Войдите через бота или откройте дневник.',[[{'text':'Открыть расписание','web_app':{'url':get_public_url()}}]])
    state={'step':'invite' if language in ('ru','en','zh') else 'language','language':language if language in ('ru','en','zh') else 'ru','nonce':secrets.token_urlsafe(8)};save(platform,user,state)
    if state['step']=='invite':return request_admission(tg,platform,user,state)
    return send(tg,'Выберите язык регистрации',[[{'text':'Русский','callback_data':'reg:'+state['nonce']+':lang:ru'},{'text':'English','callback_data':'reg:'+state['nonce']+':lang:en'},{'text':'中文','callback_data':'reg:'+state['nonce']+':lang:zh'}]])
def request_admission(tg,platform,user,state):
    from services.admissions import available_grant
    if platform=='telegram' and available_grant(user):
        state.update(step='name',invite='');save(platform,user,state)
        return send(tg,'Администратор разрешил регистрацию вашему Telegram ID. Напишите имя и фамилию для дневника.',language=state['language'])
    return send(tg,'Введите код приглашения администратора. Отмена: /cancel',language=state['language'])
def consent_message(tg,state):
    language=state['language'];root=get_public_url()+'/legal/';nonce=state['nonce']
    return send(tg,'Подтвердите условия и обработку данных отдельно. Согласия не отмечены заранее. Для завершения нужны оба подтверждения.',[
        [{'text':'Прочитать условия','url':root+'terms?lang='+language},{'text':'Прочитать согласие','url':root+('guardian' if state['age']=='minor' else 'consent')+'?lang='+language}],
        [{'text':('✓ ' if state.get('terms') else '○ ')+'Принимаю условия использования','callback_data':'reg:'+nonce+':terms'}],
        [{'text':('✓ ' if state.get('privacy') else '○ ')+'Отдельно согласен на обработку моих данных','callback_data':'reg:'+nonce+':privacy'}],
        [{'text':'Завершить регистрацию','callback_data':'reg:'+nonce+':finish'},{'text':'Отмена','callback_data':'reg:'+nonce+':cancel'}]
    ],language)
def create_account(platform,user,state):
    from services.legal import version,archive
    from services.midiary import invitation_hash,initialize as initialize_invites
    from services.privacy import record_consent
    if not state.get('terms') or not state.get('privacy') or state.get('version')!=version():raise ValueError('Подтвердите актуальные условия и согласие.')
    initialize_invites();consent=archive();code=secrets.token_urlsafe(24);owner='member:'+code
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if state['version']!=version():raise ValueError('Условия изменились. Начните регистрацию заново командой /register.')
        if platform=='telegram':
            if user in ADMIN_IDS or c.execute('SELECT 1 FROM members WHERE tg=?',(user,)).fetchone():raise ValueError('У вас уже есть аккаунт. Войдите через бота или откройте дневник.')
        elif c.execute('SELECT 1 FROM max_identities WHERE user_id=?',(user,)).fetchone():raise ValueError('У вас уже есть аккаунт. Войдите через бота или откройте дневник.')
        from services.admissions import consume,set_profile
        group=consume(c,owner,code=state.get('invite',''),tg=user if platform=='telegram' else None,minor=state['age']=='minor',consent=consent)
        c.execute('INSERT INTO members(code,name,tg) VALUES(?,?,?)',(code,state['name'],user if platform=='telegram' else None))
        set_profile(c,owner,group)
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('study_choice:'+owner,'1'))
        if platform=='max':
            from services.max_platform import bind
            bind(c,user,owner)
        record_consent(c,owner,'terms',consent);record_consent(c,owner,'guardian' if state['age']=='minor' else 'privacy',consent)
        c.execute('DELETE FROM bot_registrations WHERE platform=? AND user_id=?',(platform,user))
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('language_'+owner,state['language']))
    return owner
def message(tg,text):
    platform,user=context(tg);state=load(platform,user)
    if not state:return False
    if text.strip() in ('/cancel','/start','/link') or text.startswith('/link '):
        clear(platform,user)
        if text.strip()=='/cancel':send(tg,'Регистрация отменена.',language=state['language']);return True
        return False
    if text.startswith('/'):return False
    language=state['language']
    if state['step']=='invite':
        code=text.strip()
        if not 10<=len(code)<=100:send(tg,'Введите код приглашения администратора.',language=language);return True
        from services.admissions import invitation,initialize as initialize_invites
        initialize_invites()
        try:
            with central_db() as c:invitation(c,code)
        except ValueError as error:send(tg,str(error),language=language);return True
        state.update(invite=code,step='name');save(platform,user,state);send(tg,'Напишите имя и фамилию для дневника.',language=language);return True
    if state['step']=='name':
        name=' '.join(text.split())
        if not 2<=len(name)<=200:send(tg,'Имя должно содержать от 2 до 200 символов.',language=language);return True
        state.update(name=name,step='age');save(platform,user,state)
        send(tg,'Выберите возрастную категорию',[[{'text':'Мне 18 лет или больше','callback_data':'reg:'+state['nonce']+':age:adult'},{'text':'Мне меньше 18 лет','callback_data':'reg:'+state['nonce']+':age:minor'}]],language);return True
    send(tg,'Продолжите регистрацию кнопками выше. Отмена: /cancel',language=language);return True
def callback(value):
    tg=value['from']['id'];message=value.get('message',{})
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg:return
    if value.get('data')=='reg:start':return start(tg)
    platform,user=context(tg);parts=value.get('data','').split(':');state=load(platform,user)
    from services.telegram import tg_call
    if not state or len(parts)<3 or parts[1]!=state['nonce']:return tg_call('answerCallbackQuery',callback_query_id=value['id'],text='Запрос истёк. Начните регистрацию заново командой /register.')
    action=parts[2];language=state['language']
    tg_call('answerCallbackQuery',callback_query_id=value['id'])
    if action=='cancel':clear(platform,user);return send(tg,'Регистрация отменена.',language=language)
    if action=='lang' and state['step']=='language' and len(parts)==4 and parts[3] in ('ru','en','zh'):
        state.update(language=parts[3],step='invite');save(platform,user,state);return request_admission(tg,platform,user,state)
    if action=='age' and state['step']=='age' and len(parts)==4 and parts[3] in ('adult','minor'):
        from services.legal import version
        state.update(age=parts[3],step='consent',version=version(),terms=False,privacy=False)
        save(platform,user,state);return consent_message(tg,state)
    if state['step']=='consent':
        if action in ('terms','privacy'):state[action]=not state[action];save(platform,user,state);return consent_message(tg,state)
        if action=='finish':
            try:create_account(platform,user,state)
            except ValueError as error:return send(tg,str(error),language=language)
            return send(tg,'Регистрация завершена. Группа назначена администратором. Откройте дневник. Для входа с сайта подтвердите запрос в этом боте.',[[{'text':'Открыть расписание','web_app':{'url':get_public_url()}}]],language)
