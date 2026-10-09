"""Opt-in device notifications, independent of Telegram and its reminder preferences."""
import base64,hashlib,json,sys,time,threading
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlsplit
from config import DATA_DIR,ADMIN_IDS,MOSCOW_TZ,get_public_url
from database import get_setting
from services.community import db as group_db,filtered_days,events
from database import central_db as db,owner_profile,group_context

VENDOR=Path(__file__).resolve().parents[1]/'vendor'/'webpush'
if VENDOR.is_dir():sys.path.insert(0,str(VENDOR))

def initialize():
    with db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS web_push_devices(id TEXT PRIMARY KEY,owner TEXT NOT NULL,subscription TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS web_push_owner ON web_push_devices(owner);
    CREATE TABLE IF NOT EXISTS web_push_preferences(owner TEXT PRIMARY KEY,lessons INTEGER NOT NULL DEFAULT 1,deadlines INTEGER NOT NULL DEFAULT 1,lesson_minutes INTEGER NOT NULL DEFAULT 0,deadline_minutes INTEGER NOT NULL DEFAULT 60);
    CREATE TABLE IF NOT EXISTS web_push_deliveries(device TEXT,event TEXT,state TEXT NOT NULL,attempts INTEGER NOT NULL,next_at REAL NOT NULL,sent_at REAL,PRIMARY KEY(device,event));
    ''')

def b64(data):return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def unb64(value):
    if not isinstance(value,str):raise ValueError('Invalid key')
    return base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)

def vapid_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT value FROM settings WHERE key='web_push_private'").fetchone()
        if row:private=serialization.load_pem_private_key(row[0].encode(),None)
        else:
            private=ec.generate_private_key(ec.SECP256R1())
            pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
            c.execute("INSERT INTO settings VALUES('web_push_private',?)",(pem,))
        public=b64(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))
    return private,public

def validate_subscription(value):
    from cryptography.hazmat.primitives.asymmetric import ec
    if not isinstance(value,dict):raise ValueError('Invalid subscription')
    endpoint=value.get('endpoint');keys=value.get('keys')
    if not isinstance(endpoint,str) or not 1<=len(endpoint)<=2048 or not isinstance(keys,dict):raise ValueError('Invalid subscription')
    url=urlsplit(endpoint);host=url.hostname or ''
    allowed=host in ('web.push.apple.com','fcm.googleapis.com','updates.push.services.mozilla.com') or host.endswith('.notify.windows.com')
    if url.scheme!='https' or not allowed or url.port not in (None,443) or url.username or url.password or url.fragment or not url.path or any(ord(ch)<33 for ch in endpoint):raise ValueError('Unsupported push provider')
    if not isinstance(keys.get('p256dh'),str) or len(keys['p256dh'])>100 or not isinstance(keys.get('auth'),str) or len(keys['auth'])>32:raise ValueError('Invalid key')
    point=unb64(keys.get('p256dh'));auth=unb64(keys.get('auth'))
    if len(point)!=65 or len(auth)!=16:raise ValueError('Invalid key size')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),point)
    return {'endpoint':endpoint,'keys':{'p256dh':b64(point),'auth':b64(auth)}}

def device_id(subscription):return hashlib.sha256(subscription['endpoint'].encode()).hexdigest()

def preferences(owner):
    with db() as c:row=c.execute('SELECT * FROM web_push_preferences WHERE owner=?',(owner,)).fetchone()
    result={key:row[key] for key in ('lessons','deadlines','lesson_minutes','deadline_minutes')} if row else {'lessons':1,'deadlines':1,'lesson_minutes':0,'deadline_minutes':60}
    from services.midiary import offsets
    result['lesson_offsets']=offsets(owner,'push:lessons',[result['lesson_minutes']])
    result['deadline_offsets']=offsets(owner,'push:deadlines',[result['deadline_minutes']])
    return result

def subscribe(owner,subscription):
    subscription=validate_subscription(subscription);ident=device_id(subscription);now=time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT owner FROM web_push_devices WHERE id=?',(ident,)).fetchone()
        if old and old['owner']!=owner:c.execute('DELETE FROM web_push_deliveries WHERE device=?',(ident,))
        count=c.execute('SELECT count(*) FROM web_push_devices WHERE owner=? AND id<>?',(owner,ident)).fetchone()[0]
        if count>=10:raise ValueError('Too many devices')
        c.execute('INSERT INTO web_push_devices VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,subscription=excluded.subscription,updated=excluded.updated',(ident,owner,json.dumps(subscription),now,now))
        c.execute('INSERT OR IGNORE INTO web_push_preferences(owner) VALUES(?)',(owner,))
    return ident

def unsubscribe(owner,ident):
    with db() as c:
        row=c.execute('SELECT id FROM web_push_devices WHERE id=? AND owner=?',(ident,owner)).fetchone()
        if row:
            c.execute('DELETE FROM web_push_devices WHERE id=?',(ident,));c.execute('DELETE FROM web_push_deliveries WHERE device=?',(ident,))

def active_owners():
    admins={int(x) for x in ADMIN_IDS}
    with db() as c:
        owners={'member:'+r['code']:dict(r) for r in c.execute('SELECT code,tg,english FROM members WHERE active=1') if r['tg'] is None or int(r['tg']) not in admins}
    for tg in admins:owners['admin:'+str(tg)]={'english':get_setting('english_'+str(tg))}
    return owners

def transport(subscription,payload,ttl):
    from pywebpush import webpush
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    import requests
    private,_=vapid_keys()
    vapid=Vapid.from_pem(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    class NoRedirectSession(requests.Session):
        def request(self,*args,**kwargs):
            kwargs['allow_redirects']=False
            return super().request(*args,**kwargs)
    with NoRedirectSession() as session:
        response=webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=vapid,
            vapid_claims={'sub':get_public_url()},ttl=ttl,timeout=8,headers={'Urgency':'high'},requests_session=session)
        if not 200<=response.status_code<300:raise RuntimeError('Push provider did not accept notification')

def deliver(device,key,payload,now,expires):
    from services.privacy import blocked
    if blocked(device['owner']):return 'disabled'
    stamp=now.timestamp()
    if stamp>=expires:return 'expired'
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT owner FROM web_push_devices WHERE id=?',(device['id'],)).fetchone()
        if not current or current['owner']!=device['owner']:return 'disabled'
        record=c.execute('SELECT * FROM web_push_deliveries WHERE device=? AND event=?',(device['id'],key)).fetchone()
        if record and (record['state']=='sent' or record['next_at']>stamp):return 'waiting'
        attempt=record['attempts']+1 if record else 1
        c.execute('INSERT INTO web_push_deliveries VALUES(?,?,?,?,?,NULL) ON CONFLICT(device,event) DO UPDATE SET state=excluded.state,attempts=excluded.attempts,next_at=excluded.next_at',(device['id'],key,'sending',attempt,stamp+60))
    try:
        subscription=validate_subscription(json.loads(device['subscription']))
        from services.i18n import owner_language,translate_payload
        transport(subscription,translate_payload(payload,owner_language(device['owner'])),max(1,min(3600,int(expires-stamp))))
    except Exception as error:
        response=getattr(error,'response',None);status=getattr(response,'status_code',0)
        if status in (404,410):unsubscribe(device['owner'],device['id']);return 'removed'
        delay=min(900,15*(2**min(attempt,6)))
        if status==429:
            try:delay=max(delay,min(3600,int(response.headers.get('Retry-After',delay))))
            except (ValueError,TypeError):pass
        with db() as c:c.execute('UPDATE web_push_deliveries SET state=?,next_at=? WHERE device=? AND event=?',('retry',stamp+delay,device['id'],key))
        return 'retry'
    with db() as c:c.execute('UPDATE web_push_deliveries SET state=?,sent_at=?,next_at=? WHERE device=? AND event=?',('sent',stamp,expires,device['id'],key))
    return 'sent'

def single_candidates(owner,member,prefs,now,marker=None):
    from urllib.parse import urlencode
    group=get_setting('group_id')
    def entry(key,title,body,begins,minutes,path):
        if begins-timedelta(minutes=minutes)<=now<begins-timedelta(minutes=minutes)+timedelta(minutes=3):
            payload={'title':title,'body':body,'tag':'fgu-'+hashlib.sha256(key.encode()).hexdigest()[:32],'url':'/?'+urlencode(path)}
            return key,payload,(begins-timedelta(minutes=minutes)+timedelta(minutes=3)).timestamp()
    result=[]
    if prefs['lessons']:
        from services.group_comparison import shared_marker,record
        if marker is None:
            try:marker=shared_marker(owner,now)
            except Exception:marker=lambda lesson:''
        first=now.date().isoformat();last=(now+timedelta(days=1)).date().isoformat();lessons=[]
        with group_db() as c:raw=[json.loads(r[0]) for r in c.execute('SELECT body FROM schedules WHERE group_id=? AND day BETWEEN ? AND ?',(group,first,last))]
        for day in filtered_days(owner,raw):
            for lesson in day.get('lessons',[]):
                for p in lesson.get('periods',[]):
                    lessons.append(record(day['date'],lesson,p)|{'id':p['_diary_id'],'_lesson':True})
        lessons+=events(owner,first,last)
        for lesson in lessons:
            try:begins=datetime.fromisoformat(lesson['date']+'T'+lesson['start']).replace(tzinfo=MOSCOW_TZ)
            except (ValueError,KeyError,TypeError):continue
            key=json.dumps(['lesson',group,lesson['id'],begins.isoformat(),prefs['lesson_minutes']])
            clock=begins.strftime('%H:%M');body=str(lesson.get('title') or 'Пара')+' · '+clock+' (МСК)'+(' · '+str(lesson['room']) if lesson.get('room') else '')
            from services.teachers import teacher_list
            metadata={'date':lesson['date'],'start':lesson['start'],'end':lesson.get('end',''),
                      'title':lesson.get('title',''),'room':lesson.get('room',''),
                      'teachers':teacher_list(lesson.get('teachers') or lesson.get('teacher'))}
            notice=marker(metadata) if lesson.get('_lesson') or lesson.get('type')=='lesson' else ''
            if notice:body+='\n'+notice
            e=entry(key,'Начало пары' if now>=begins else 'Скоро пара',body,begins,prefs['lesson_minutes'],{'view':'day','date':lesson['date']})
            if e:result.append(e)
    if prefs['deadlines']:
        with group_db() as c:deadlines=list(c.execute('SELECT * FROM deadlines WHERE group_name=?',(get_setting('group_name'),)))
        for deadline in deadlines:
            try:
                due=datetime.fromisoformat(deadline['due'])
                if due.tzinfo is None:continue
            except (ValueError,TypeError):continue
            key=json.dumps(['deadline',group,deadline['item'],deadline['due'],prefs['deadline_minutes']])
            e=entry(key,'Дедлайн',deadline['title']+' · до '+due.astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')+' (МСК)',due,prefs['deadline_minutes'],{'view':'deadlines'})
            if e:result.append(e)
    return result

def candidates(owner,member,prefs,now):
    from services.notification_channels import enabled
    if not enabled(owner,'website'):return []
    from services.midiary import offsets
    from services.group_comparison import shared_marker
    try:marker=shared_marker(owner,now) if prefs['lessons'] else lambda lesson:''
    except Exception:marker=lambda lesson:''
    result=[]
    for kind,other,field in (('lessons','deadlines','lesson'),('deadlines','lessons','deadline')):
        if not prefs[kind]:continue
        values=prefs.get(field+'_offsets',offsets(owner,'push:'+kind,[prefs[field+'_minutes']]))
        for value in values:
            config=dict(prefs);config[other]=0;config[field+'_minutes']=value
            result.extend(single_candidates(owner,member,config,now,marker))
    from services.homework_reminders import candidates as homework_candidates
    result.extend(homework_candidates(owner,member,now))
    from services.group_comparison import candidates as comparison_candidates
    for item in comparison_candidates(owner,now):
        if item['channels']['website']:
            payload={'title':item['title'],'body':item['body'],'tag':item['key'],
                     'url':'/?view=day&date='+item['date']+'&compare=1'}
            result.append((item['key'],payload,item['expires']))
    return result

def check_push(at=None):
    now=at or datetime.now(MOSCOW_TZ);owners=active_owners();result={'devices':0,'sent':0,'retry':0,'removed':0,'errors':0};cache={}
    with db() as c:devices=[dict(r) for r in c.execute('SELECT * FROM web_push_devices')]
    for device in devices:
        owner=device['owner']
        if owner not in owners:unsubscribe(owner,device['id']);continue
        result['devices']+=1
        try:
            if owner not in cache:
                profile=owner_profile(owner)
                if not profile or not profile['group_id']:continue
                with group_context(profile['group_id']):cache[owner]=candidates(owner,owners[owner],preferences(owner),now)
            from services.i18n import owner_language,translate_payload
            for key,payload,expires in cache[owner]:
                payload=translate_payload(payload,owner_language(owner))
                state=deliver(device,key,payload,now,expires)
                if state in result:result[state]+=1
        except Exception:result['errors']+=1
    with db() as c:c.execute('DELETE FROM web_push_deliveries WHERE next_at<?',(now.timestamp()-30*86400,))
    return result

def start_worker(stop):
    def loop():
        while not stop.is_set():
            try:
                result=check_push();result['checked_at']=time.time()
                path=DATA_DIR/'web-push-health.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result));temporary.replace(path)
            except Exception:pass
            stop.wait(15)
    threading.Thread(target=loop,args=(),name='WebPushWorker',daemon=True).start()

initialize()
