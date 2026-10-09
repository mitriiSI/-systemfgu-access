"""Account controls and an idempotent deletion queue. Never deletes another account."""
import hashlib,hmac,json,os,re,threading,time
from pathlib import Path
from flask import Blueprint,abort,jsonify,request,session,Response
from config import DATA_DIR,SESSION_SECRET
from database import central_db,connect,DB_PATH,utc_now

privacy_bp=Blueprint('privacy',__name__)
deletion_lock=threading.Lock()

def initialize():
    with central_db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS privacy_consents(owner TEXT,kind TEXT,version TEXT,accepted TEXT,PRIMARY KEY(owner,kind,version));
    CREATE TABLE IF NOT EXISTS privacy_file_owners(id TEXT PRIMARY KEY,owner TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS privacy_deletions(owner TEXT PRIMARY KEY,kind TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS privacy_documents(version TEXT PRIMARY KEY,body TEXT NOT NULL,created TEXT NOT NULL);
    ''')

def tables(c):return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def database_paths():
    root=DB_PATH.parent.resolve()
    for p in [DB_PATH]+sorted((root/'groups').glob('*.sqlite3')):
        if p.is_symlink() or not p.resolve().is_relative_to(root):raise RuntimeError('Unexpected group database path')
        if p.is_file():yield p

def erased_hash(owner):return hmac.new(SESSION_SECRET.encode(),('privacy-erased:'+owner).encode(),hashlib.sha256).hexdigest()
def erased_owners():
    p=DATA_DIR/'privacy-erased.json'
    try:
        values=json.loads(p.read_text())
        if not isinstance(values,list) or not all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in values):raise ValueError('Invalid erasure registry')
        return set(values)
    except FileNotFoundError:return set()

def save_erasure(owner):
    values=erased_owners();values.add(erased_hash(owner));p=DATA_DIR/'privacy-erased.json';tmp=p.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as stream:
        stream.write(json.dumps(sorted(values)));stream.flush();os.fsync(stream.fileno())
    tmp.chmod(0o600);tmp.replace(p)
    if os.name!='nt':
        descriptor=os.open(str(DATA_DIR),os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

def blocked(owner):
    with central_db() as c:return bool(c.execute("SELECT 1 FROM privacy_deletions WHERE owner=? AND kind='account'",(owner,)).fetchone()) or erased_hash(owner) in erased_owners()

def remember_file(ident,owner):
    initialize()
    with central_db() as c:c.execute('INSERT OR REPLACE INTO privacy_file_owners VALUES(?,?)',(ident,owner))

def record_consent(c,owner,kind,version):
    c.execute('INSERT OR REPLACE INTO privacy_consents VALUES(?,?,?,?)',(owner,kind,version,utc_now()))

def delete_rows(c,table,column,value):
    if table in tables(c):c.execute(f'DELETE FROM {table} WHERE {column}=?',(value,))

def process_one(owner,kind):
    initialize()
    with central_db() as c:
        member=c.execute('SELECT * FROM members WHERE code=?',(owner.removeprefix('member:'),)).fetchone() if owner.startswith('member:') else None
        name=member['name'] if member else ''
        unique_name=bool(member) and c.execute('SELECT count(*) FROM members WHERE name=?',(name,)).fetchone()[0]==1
        files={r[0] for r in c.execute('SELECT id FROM privacy_file_owners WHERE owner=?',(owner,))} if kind=='account' else set()
        attributed={r[0] for r in c.execute('SELECT id FROM privacy_file_owners')}
        tg=member['tg'] if member else None
    all_paths=list(database_paths());removed_files=set(files)
    for path in all_paths:
        c=connect(path)
        try:
            with c:
                existing=tables(c)
                for table in ('personal','hidden_lessons','custom_lessons','custom_lesson_history','lesson_times','lesson_rooms','reminder_prefs','deadline_subs','reminder_sent','reminder_delivery','schedule_imports'):delete_rows(c,table,'owner',owner)
                for row in c.execute('SELECT key FROM settings').fetchall() if 'settings' in existing else []:
                    key=row['key']
                    if key in ('theme_'+owner,'language_'+owner,'midiary_import_choices:'+owner) or key.startswith('midiary_offsets:'+owner+':'):c.execute('DELETE FROM settings WHERE key=?',(key,))
                if kind=='account':
                    if 'files' in existing:
                        for row in c.execute('SELECT id,author FROM files').fetchall():
                            if row['id'] in files or (row['id'] not in attributed and unique_name and row['author']==name):
                                if path==DB_PATH:c.execute('INSERT OR REPLACE INTO privacy_file_owners VALUES(?,?)',(row['id'],owner))
                                else:remember_file(row['id'],owner)
                                c.execute('DELETE FROM files WHERE id=?',(row['id'],));removed_files.add(row['id'])
                    for table in ('content','revisions','proposals'):
                        if name and table in existing:c.execute(f'UPDATE {table} SET author=? WHERE author=?',('Удалённый участник',name))
                    delete_rows(c,'teacher_reviews','owner',owner)
                    if 'content' in existing:
                        for row in c.execute("SELECT item,body FROM content WHERE kind='schedule_event'").fetchall():
                            try:event=json.loads(row['body'])
                            except ValueError:continue
                            if isinstance(event,dict) and event.get('creator')==owner:
                                event['creator']='deleted';c.execute("UPDATE content SET body=? WHERE kind='schedule_event' AND item=?",(json.dumps(event,ensure_ascii=False),row['item']))
        finally:c.close()
    # Only unlink a genuine app upload after all group references have been checked.
    for ident in removed_files:
        referenced=False
        for path in all_paths:
            c=connect(path)
            try:
                if 'files' in tables(c) and c.execute('SELECT 1 FROM files WHERE id=?',(ident,)).fetchone():referenced=True
            finally:c.close()
        if not referenced and re.fullmatch('[a-f0-9]{48}',ident):
            root=(DATA_DIR/'files').resolve();p=root/ident
            if p.is_symlink() or not p.resolve().is_relative_to(root):raise RuntimeError('Unexpected file path')
            p.unlink(missing_ok=True)
    with central_db() as c:
        device_ids=[r[0] for r in c.execute('SELECT id FROM web_push_devices WHERE owner=?',(owner,))]
        for ident in device_ids:delete_rows(c,'web_push_deliveries','device',ident)
        for table in ('web_push_devices','web_push_preferences','midiary_text_translations','history_points'):delete_rows(c,table,'owner',owner)
        delete_rows(c,'group_comparison_messages','recipient',owner)
        for row in c.execute('SELECT key FROM settings').fetchall():
            key=row['key']
            if key in ('language_'+owner,'onboarding_v1_'+owner) or key.startswith(('midiary_offsets:'+owner+':','midiary_subgroups:'+owner+':')):c.execute('DELETE FROM settings WHERE key=?',(key,))
        if kind=='account':
            delete_rows(c,'group_comparison_access','owner',owner)
            delete_rows(c,'group_comparison_access','peer_owner',owner)
            # Keep the digest outside SQLite backups so restoring a snapshot cannot revive an erased account.
            save_erasure(owner)
            code=owner.removeprefix('member:')
            for key in ('moderate_'+code,'english_'+str(tg),'privacy_broadcast_'+owner):c.execute('DELETE FROM settings WHERE key=?',(key,))
            for table in ('faculty_reviews','privacy_consents','privacy_file_owners','university_profiles','account_activity'):delete_rows(c,table,'owner',owner)
            if 'max_identities' in tables(c):
                max_ids=[r[0] for r in c.execute('SELECT user_id FROM max_identities WHERE owner=?',(owner,))]
                for user_id in max_ids:
                    for table in ('max_attempts','max_logins','max_broadcast_deliveries','max_events'):delete_rows(c,table,'user_id',user_id)
                    delete_rows(c,'max_account_links','max_id',user_id)
                    if 'bot_registrations' in tables(c):c.execute("DELETE FROM bot_registrations WHERE platform='max' AND user_id=?",(user_id,))
                delete_rows(c,'max_identities','owner',owner)
                c.execute('DELETE FROM settings WHERE key=?',('max_delivery_disabled:'+owner,))
            delete_rows(c,'max_file_tickets','owner',owner)
            delete_rows(c,'max_account_links','tg_id',tg)
            if 'bot_registrations' in tables(c):c.execute("DELETE FROM bot_registrations WHERE platform='telegram' AND user_id=?",(tg,))
            delete_rows(c,'attempts','tg',tg);delete_rows(c,'browser_logins','tg',tg);delete_rows(c,'broadcast_deliveries','tg',tg)
            delete_rows(c,'telegram_events','user_id',tg)
            if 'midiary_invites' in tables(c):c.execute('UPDATE midiary_invites SET used_by=NULL WHERE used_by=?',(owner,))
            delete_rows(c,'midiary_invite_uses','owner',owner)
            delete_rows(c,'telegram_registration_grants','used_by',owner)
            delete_rows(c,'telegram_registration_grants','tg',tg)
            delete_rows(c,'subscription_overrides','owner',owner)
            c.execute('DELETE FROM members WHERE code=?',(code,))
        c.execute('DELETE FROM privacy_deletions WHERE owner=? AND kind=?',(owner,kind))

def process_pending():
    if not deletion_lock.acquire(blocking=False):return {'processed':0,'failed':0}
    result={'processed':0,'failed':0}
    try:
        initialize();hashes=erased_owners()
        from services.bot_registration import purge
        from services.max_account_link import initialize as purge_links
        purge();purge_links()
        with central_db() as c:
            for row in c.execute('SELECT code FROM members').fetchall():
                owner='member:'+row['code']
                if erased_hash(owner) in hashes:c.execute("INSERT OR IGNORE INTO privacy_deletions VALUES(?,'account',?)",(owner,time.time()))
            jobs=[dict(r) for r in c.execute('SELECT * FROM privacy_deletions ORDER BY created LIMIT 10')]
        for job in jobs:
            try:process_one(job['owner'],job['kind']);result['processed']+=1
            except Exception:result['failed']+=1 # Retain the queue entry; retry without logging personal content.
    finally:deletion_lock.release()
    return result

def start_worker(stop):
    def loop():
        while not stop.is_set():
            try:
                result=process_pending()
                with central_db() as c:result['pending']=c.execute('SELECT count(*) FROM privacy_deletions').fetchone()[0]
                result['checked_at']=time.time();path=DATA_DIR/'privacy-health.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result),encoding='utf-8');temp.replace(path)
            except Exception:pass
            stop.wait(30)
    threading.Thread(target=loop,daemon=True,name='PrivacyMaintenance').start()

@privacy_bp.get('/api/account/export')
def export():
    from routes.auth import get_current_member,get_personal_owner
    member=get_current_member();owner=get_personal_owner();initialize()
    result={'account':{k:member.get(k) for k in ('name','tg','english')},'groups':[]}
    with central_db() as c:
        result['profile']=dict(c.execute('SELECT * FROM university_profiles WHERE owner=?',(owner,)).fetchone() or {})
        result['profile'].pop('owner',None)
        if 'account_activity' in tables(c):
            activity=c.execute('SELECT last_seen FROM account_activity WHERE owner=?',(owner,)).fetchone()
            result['activity']={'last_seen':activity['last_seen'] if activity else None}
        result['reviews']=[{k:r[k] for k in r.keys() if k not in ('owner','id')} for r in c.execute('SELECT * FROM faculty_reviews WHERE owner=?',(owner,))]
        result['consents']=[{k:r[k] for k in ('kind','version','accepted')} for r in c.execute('SELECT * FROM privacy_consents WHERE owner=?',(owner,))]
        own_files={r[0] for r in c.execute('SELECT id FROM privacy_file_owners WHERE owner=?',(owner,))}
        result['notifications']={'announcements':__import__('database').central_setting('privacy_broadcast_'+owner,'1')=='1'}
        if 'history_points' in tables(c):
            from services.history_points import public_entry
            result['history_points']=[public_entry(row)|{'group_id':row['group_id']}
                for row in c.execute('SELECT * FROM history_points WHERE owner=? ORDER BY date DESC',(owner,))]
        from services.group_comparison import allowed,preferences,active_note,integrated
        if allowed(owner):
            result['notifications']['group_comparison']=preferences(owner)
            result['notifications']['group_comparison']['integrated']=integrated(owner)
            result['comparison_note']=active_note(owner)
        result['subgroups']={r['key'].removeprefix('midiary_subgroups:'+owner+':'):json.loads(r['value'])
                             for r in c.execute('SELECT key,value FROM settings') if r['key'].startswith('midiary_subgroups:'+owner+':')}
        if 'max_identities' in tables(c):
            row=c.execute('SELECT user_id FROM max_identities WHERE owner=?',(owner,)).fetchone()
            result['account']['max_user_id']=row['user_id'] if row else None
        result['files']=[]
    for path in database_paths():
        c=connect(path)
        try:
            data={}
            for table in ('personal','custom_lessons','hidden_lessons','lesson_times','lesson_rooms','reminder_prefs','deadline_subs'):
                if table in tables(c):data[table]=[{k:r[k] for k in r.keys() if k!='owner'} for r in c.execute(f'SELECT * FROM {table} WHERE owner=?',(owner,))]
            if 'settings' in tables(c):
                choices=c.execute('SELECT value FROM settings WHERE key=?',('midiary_import_choices:'+owner,)).fetchone()
                if choices:data['import_choices']=json.loads(choices[0])
            if any(data.values()):result['groups'].append(data)
            if 'files' in tables(c):result['files'].extend({k:r[k] for k in r.keys() if k not in ('id','author')} for r in c.execute('SELECT * FROM files') if r['id'] in own_files)
        finally:c.close()
    return Response(json.dumps(result,ensure_ascii=False),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="midiary-my-data.json"'})

@privacy_bp.post('/api/account/delete')
def delete_account():
    from routes.auth import get_current_member,get_personal_owner
    member=get_current_member();owner=get_personal_owner();body=request.get_json() or {};kind=body.get('kind','account')
    if body.get('confirm') is not True or kind not in ('account','personal'):abort(400)
    if member['admin'] and kind=='account':return jsonify(error='Сначала передайте права администратора. Здесь можно удалить личные записи.'),409
    initialize()
    with central_db() as c:
        c.execute('INSERT INTO privacy_deletions VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET kind=CASE WHEN kind=\'account\' THEN kind ELSE excluded.kind END',(owner,kind,time.time()))
        if kind=='account':c.execute('UPDATE members SET active=0 WHERE code=?',(member['code'],))
    process_pending()
    with central_db() as c:pending=bool(c.execute('SELECT 1 FROM privacy_deletions WHERE owner=?',(owner,)).fetchone())
    if kind=='account':session.clear()
    return jsonify(ok=True,pending=pending),202 if pending else 200

@privacy_bp.route('/api/account/announcements',methods=['GET','POST'])
def announcements():
    from routes.auth import get_personal_owner
    from database import central_setting,central_set_setting
    owner=get_personal_owner()
    if request.method=='POST':
        value=(request.get_json() or {}).get('enabled')
        if type(value) is not bool:abort(400)
        central_set_setting('privacy_broadcast_'+owner,'1' if value else '0')
    return jsonify(enabled=central_setting('privacy_broadcast_'+owner,'1')=='1')

def accepts_announcements(tg):
    from database import central_setting
    with central_db() as c:member=c.execute('SELECT code FROM members WHERE tg=? AND active=1',(tg,)).fetchone()
    return bool(member) and central_setting('privacy_broadcast_member:'+member['code'],'1')=='1' and not blocked('member:'+member['code'])
