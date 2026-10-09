"""MAX transport and verified bindings to existing Midiary owners."""
import hashlib,hmac,json,os,re,time,threading
from pathlib import Path
from urllib.parse import parse_qsl,urlsplit,parse_qs
import requests
from config import DATA_DIR,SESSION_SECRET,ADMIN_IDS,get_public_url
from database import central_db,central_setting,owner_profile

API='https://platform-api2.max.ru'
BOT_USERNAME='se13528019_1_bot'
_rate_lock=threading.Lock()
_next_request=0.0
_next_recipient={}

class MaxAPIError(RuntimeError):
    def __init__(self,status,code='request.failed'):
        self.code=status;self.max_code=str(code)[:80]
        super().__init__('MAX API status '+str(status))

def credentials():
    try:
        path=DATA_DIR/'max-credentials.json'
        if path.is_symlink():raise RuntimeError('Unexpected MAX credentials path')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict):raise ValueError()
    except FileNotFoundError:value={}
    return {'token':os.getenv('MAX_BOT_TOKEN') or value.get('token',''),
            'secret':os.getenv('MAX_WEBHOOK_SECRET') or value.get('secret',''),
            'ca_bundle':os.getenv('MAX_CA_BUNDLE') or value.get('ca_bundle') or str(Path(__file__).with_name('max_root_ca.pem'))}

def configured():
    value=credentials();return bool(value['token'] and value['secret'])

def call(method,path,*,params=None,body=None):
    global _next_request
    value=credentials()
    if not value['token']:raise RuntimeError('MAX is not configured')
    if not re.fullmatch(r'/[a-zA-Z0-9_/-]+',path):raise ValueError('Invalid MAX API path')
    with _rate_lock:
        now=time.monotonic();recipient=(params or {}).get('user_id') if method=='POST' and path=='/messages' else None
        slot=max(now,_next_request,_next_recipient.get(recipient,0) if recipient is not None else 0)
        _next_request=slot+.05
        if recipient is not None:_next_recipient[recipient]=slot+.51
    if slot>now:time.sleep(slot-now)
    from services.network_trust import certificate_bundle
    response=requests.request(method,API+path,headers={'Authorization':value['token']},
        params=params,json=body,timeout=(8,35),verify=certificate_bundle(value['ca_bundle']),allow_redirects=False)
    try:result=response.json()
    except ValueError:raise MaxAPIError(response.status_code) from None
    if response.status_code>=400 or not isinstance(result,dict) or result.get('success') is False or result.get('code'):
        raise MaxAPIError(response.status_code,result.get('code','request.failed') if isinstance(result,dict) else 'request.failed')
    return result

def initialize():
    with central_db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS max_identities(user_id INTEGER PRIMARY KEY,owner TEXT UNIQUE NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS max_attempts(user_id INTEGER PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS max_logins(token TEXT PRIMARY KEY,expires REAL NOT NULL,status TEXT NOT NULL DEFAULT 'pending',user_id INTEGER);
    CREATE TABLE IF NOT EXISTS max_events(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS max_broadcasts(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,message_id TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,notified INTEGER NOT NULL DEFAULT 0,UNIQUE(owner,message_id));
    CREATE TABLE IF NOT EXISTS max_broadcast_deliveries(job INTEGER,user_id INTEGER,recipient_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,PRIMARY KEY(job,user_id));
    CREATE TABLE IF NOT EXISTS max_file_tickets(hash TEXT PRIMARY KEY,owner TEXT NOT NULL,group_id TEXT NOT NULL,file_id TEXT NOT NULL,expires REAL NOT NULL);
    ''')

def valid_user_id(value):
    if type(value) is not int or not 0<value<2**63:raise ValueError('Invalid MAX identity')
    return value

def parse_user(raw):
    if not isinstance(raw,str) or not 1<=len(raw)<=16384:raise ValueError('Invalid launch data')
    pairs=parse_qsl(raw,keep_blank_values=True,strict_parsing=True)
    if len(pairs)!=len(dict(pairs)):raise ValueError('Duplicate launch fields')
    fields=dict(pairs);given=fields.pop('hash','');token=credentials()['token']
    if not token or not re.fullmatch('[a-fA-F0-9]{64}',given):raise ValueError('Invalid launch signature')
    key=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    expected=hmac.new(key,'\n'.join(k+'='+v for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given.lower(),expected):raise ValueError('Invalid launch signature')
    if not -30<=time.time()-int(fields.get('auth_date','0'))<=3600:raise ValueError('Expired launch data')
    return valid_user_id(json.loads(fields['user'])['id'])

def member_for_owner(owner):
    from services.privacy import blocked
    if not isinstance(owner,str) or blocked(owner):return None
    if owner.startswith('admin:'):
        try:tg=int(owner[6:])
        except ValueError:return None
        if tg in ADMIN_IDS:return {'owner':owner,'tg':tg,'admin':True,'english':central_setting('english_'+str(tg))}
        return None
    if not owner.startswith('member:'):return None
    with central_db() as c:row=c.execute('SELECT * FROM members WHERE code=? AND active=1',(owner[7:],)).fetchone()
    return dict(row)|{'owner':owner,'admin':False} if row else None

def identity(user_id):
    with central_db() as c:row=c.execute('SELECT owner FROM max_identities WHERE user_id=?',(valid_user_id(user_id),)).fetchone()
    return member_for_owner(row['owner']) if row else None

def user_for_owner(owner):
    with central_db() as c:row=c.execute('SELECT user_id FROM max_identities WHERE owner=?',(owner,)).fetchone()
    return row['user_id'] if row and member_for_owner(owner) else None

def bind(c,user_id,owner):
    valid_user_id(user_id)
    by_user=c.execute('SELECT owner FROM max_identities WHERE user_id=?',(user_id,)).fetchone()
    by_owner=c.execute('SELECT user_id FROM max_identities WHERE owner=?',(owner,)).fetchone()
    if (by_user and by_user['owner']!=owner) or (by_owner and by_owner['user_id']!=user_id):raise PermissionError('MAX binding already exists')
    c.execute('INSERT OR IGNORE INTO max_identities VALUES(?,?,?)',(user_id,owner,time.time()))

def link_code(user_id,code):
    valid_user_id(user_id)
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM max_attempts WHERE user_id=?',(user_id,)).fetchone()
        if row and row['until']>time.time() and row['count']>=5:return 'Слишком много попыток. Попробуйте через 15 минут.'
        count=row['count']+1 if row and row['until']>time.time() else 1
        c.execute('INSERT OR REPLACE INTO max_attempts VALUES(?,?,?)',(user_id,count,time.time()+900))
        member=c.execute('SELECT code FROM members WHERE code=? AND active=1',(code,)).fetchone()
        owner='member:'+member['code'] if member else None
        if not owner:
            digest=hmac.new(SESSION_SECRET.encode(),('admin-code:'+code).encode(),hashlib.sha256).hexdigest()
            owner=next(('admin:'+str(admin) for admin in ADMIN_IDS if hmac.compare_digest(digest,central_setting('admin_code_'+str(admin),'!'))),None)
        if not owner or not member_for_owner(owner):return 'Код не найден или доступ отключён.'
        try:bind(c,user_id,owner)
        except PermissionError:return 'Аккаунт MAX уже привязан. Отвязать его можно в профиле Midiary.'
        c.execute('DELETE FROM max_attempts WHERE user_id=?',(user_id,))
    return 'MAX подключён к аккаунту и уведомлениям Midiary.'

def linked(owner):return user_for_owner(owner) is not None

def attachments(markup):
    rows=[]
    for row in (markup or {}).get('inline_keyboard',[]):
        buttons=[]
        for button in row:
            item={'text':button.get('text','')}
            if 'callback_data' in button:item.update(type='callback',payload=button['callback_data'])
            elif 'web_app' in button:
                item.update(type='open_app',web_app=BOT_USERNAME)
                if parse_qs(urlsplit(button['web_app'].get('url','')).query).get('register')==['1']:item['payload']='register'
            elif 'url' in button:item.update(type='link',url=button['url'])
            else:continue
            buttons.append(item)
        if buttons:rows.append(buttons)
    return [{'type':'inline_keyboard','payload':{'buttons':rows}}] if rows else []

def send_telegram(method,data,*,user_id,owner=None):
    from services.i18n import translate_payload,owner_language
    values=dict(data);original=values.pop('_midiary_user_content',False)
    if not original:
        # Common command wording follows the selected messenger; user text stays intact.
        if isinstance(values.get('text'),str) and 'MAX' not in values['text']:values['text']=values['text'].replace('Telegram','MAX')
        values=translate_payload(values,owner_language(owner) if owner else 'ru')
    body={'text':values.get('text',''),'attachments':attachments(values.get('reply_markup'))}
    if method=='sendMessage':return call('POST','/messages',params={'user_id':valid_user_id(user_id)},body=body)
    if method=='editMessageText':return call('PUT','/messages',params={'message_id':str(values['message_id'])},body=body)
    if method=='answerCallbackQuery':return call('POST','/answers',params={'callback_id':values['callback_query_id']},body={'notification':values.get('text','')})
    raise ValueError('Unsupported messenger action')

def compatibility(method,data):
    from services.bot_context import current
    context=current.get()
    if not context or context['platform']!='max':raise RuntimeError('Missing MAX context')
    if method!='answerCallbackQuery' and data.get('chat_id')!=context['canonical']:raise PermissionError('Cross-platform recipient mismatch')
    return send_telegram(method,data,user_id=context['user_id'],owner=context.get('owner'))
