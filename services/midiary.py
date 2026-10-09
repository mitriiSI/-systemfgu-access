"""Invite-only accounts, language and multiple reminder windows."""
import hashlib,hmac,json,re,secrets,time
from flask import Blueprint,request,jsonify,abort,session
from config import SESSION_SECRET
from database import central_db,central_setting,central_set_setting,utc_now,default_group
from services.admissions import invitation_hash,initialize,create_invitation

midiary_bp=Blueprint('midiary',__name__)
LESSON_OFFSETS=(0,5,10,15,30,60,120)
DEADLINE_OFFSETS=(0,15,60,180,1440,2880)

def offsets(owner,kind,fallback=()):
    if kind.startswith('deadline:'):
        from database import current_group
        kind='deadline:'+current_group()+':'+kind[9:]
    raw=central_setting('midiary_offsets:'+owner+':'+kind)
    if not raw:return list(fallback)
    try:return json.loads(raw)
    except (TypeError,ValueError):return list(fallback)

def save_offsets(owner,kind,values,allowed):
    if not isinstance(values,list) or len(values)>len(allowed) or any(type(v) is not int or v not in allowed for v in values):raise ValueError('Invalid reminder intervals')
    if kind.startswith('deadline:'):
        from database import current_group
        kind='deadline:'+current_group()+':'+kind[9:]
    values=sorted(set(values));central_set_setting('midiary_offsets:'+owner+':'+kind,json.dumps(values));return values

@midiary_bp.post('/api/register')
def register():
    from routes.auth import browser_limit,establish
    browser_limit();b=request.get_json() or {};code=b.get('code','');name=b.get('name')
    if not isinstance(code,str) or (code and not 10<=len(code.strip())<=100) or not isinstance(name,str) or not 2<=len(name.strip())<=200:abort(400)
    from services.legal import registration_consent,version
    from services.privacy import record_consent
    consent=registration_consent(b)
    initialize()
    telegram_id=None
    max_user_id=None
    if b.get('maxInitData'):
        from routes.max_app import verified
        max_user_id=verified(b['maxInitData'])
    if b.get('initData'):
        from routes.auth import parse_telegram_user
        try:telegram_id=parse_telegram_user(b['initData'])
        except (ValueError,KeyError,TypeError):abort(401)
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if consent!=version():abort(400)
        login=c.execute("SELECT * FROM browser_logins WHERE token=? AND status='approved' AND expires>?",(session.get('login_token',''),time.time())).fetchone()
        if login:telegram_id=login['tg']
        max_login=c.execute("SELECT * FROM max_logins WHERE token=? AND status='approved' AND expires>?",(session.get('max_login_token',''),time.time())).fetchone()
        if max_login:max_user_id=max_login['user_id']
        if b.get('maxRegistration') is True and max_user_id is None:return jsonify(error='Сначала подтвердите аккаунт MAX через бота.'),400
        if max_user_id and c.execute('SELECT user_id FROM max_identities WHERE user_id=?',(max_user_id,)).fetchone():abort(409)
        if telegram_id:
            from config import ADMIN_IDS
            if telegram_id in ADMIN_IDS or c.execute('SELECT tg FROM members WHERE tg=?',(telegram_id,)).fetchone():abort(409)
        access=secrets.token_urlsafe(24);owner='member:'+access
        from services.admissions import consume,set_profile
        try:group=consume(c,owner,code=code.strip(),tg=telegram_id,minor=b['age_group']=='minor',consent=consent)
        except ValueError as error:return jsonify(error=str(error)),403
        c.execute('INSERT INTO members(code,name,tg) VALUES(?,?,?)',(access,' '.join(name.split()),telegram_id))
        set_profile(c,owner,group)
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('study_choice:'+owner,'1'))
        if max_user_id:
            from services.max_platform import bind
            bind(c,max_user_id,owner)
        record_consent(c,owner,'terms',consent)
        record_consent(c,owner,'guardian' if b['age_group']=='minor' else 'privacy',consent)
        if login:c.execute('DELETE FROM browser_logins WHERE token=?',(login['token'],))
        if max_login:c.execute('DELETE FROM max_logins WHERE token=?',(max_login['token'],))
    return establish(tg=telegram_id,max_user_id=max_user_id) if telegram_id else establish(code=access,max_user_id=max_user_id)

@midiary_bp.post('/api/admin/invites')
def invite():
    from routes.auth import get_current_member,get_personal_owner
    if not get_current_member()['admin']:abort(403)
    body=request.get_json() or {};minor=body.get('minor',False)
    if type(minor) is not bool:abort(400)
    if minor and body.get('guardian_confirmed') is not True:abort(400)
    try:code=create_invitation(get_personal_owner(),guardian=minor,count=body.get('count',1),group_id=body.get('group_id','fgu:1457'))
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(code=code,expires_days=7,minor=minor,count=body.get('count',1),id=invitation_hash(code))

@midiary_bp.get('/api/admin/admissions')
def admissions():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:abort(403)
    from services.admissions import overview
    return jsonify(overview())

@midiary_bp.post('/api/admin/registrations/telegram')
def permit_telegram():
    from routes.auth import get_current_member,get_personal_owner
    if not get_current_member()['admin']:abort(403)
    body=request.get_json() or {};minor=body.get('minor',False)
    if type(minor) is not bool or (minor and body.get('guardian_confirmed') is not True):abort(400)
    from services.admissions import allow_telegram
    try:tg=allow_telegram(get_personal_owner(),body.get('tg'),guardian=minor,group_id=body.get('group_id','fgu:1457'))
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(ok=True,tg=tg,expires_days=7)

@midiary_bp.post('/api/admin/admissions/revoke')
def revoke_admission():
    from routes.auth import get_current_member,get_personal_owner
    if not get_current_member()['admin']:abort(403)
    from services.admissions import revoke
    body=request.get_json() or {}
    try:revoke(get_personal_owner(),body.get('kind'),body.get('id'))
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(ok=True)

@midiary_bp.route('/api/admin/members',methods=['GET','POST'])
def manage_members():
    from routes.auth import get_current_member,get_personal_owner
    if not get_current_member()['admin']:abort(403)
    if request.method=='POST':
        from services.admissions import assign_member
        body=request.get_json() or {}
        if not isinstance(body.get('member'),str):abort(400)
        try:assign_member(get_personal_owner(),body['member'],body.get('group_id'))
        except ValueError as error:return jsonify(error=str(error)),400
        from services.timetable import start_sync
        start_sync(body['group_id'])
    with central_db() as c:
        rows=[dict(r) for r in c.execute('''SELECT m.code AS id,m.name,m.tg,m.active,p.faculty,p.group_id,g.name AS group_name
            FROM members m LEFT JOIN university_profiles p ON p.owner='member:'||m.code
            LEFT JOIN university_groups g ON g.id=p.group_id ORDER BY m.active DESC,m.name''')]
    return jsonify(members=rows)

@midiary_bp.post('/api/account/name')
def own_name():
    from routes.auth import get_current_member
    member=get_current_member()
    if member['admin']:abort(400)
    name=(request.get_json() or {}).get('name')
    if not isinstance(name,str):abort(400)
    name=' '.join(name.split())
    if not 2<=len(name)<=200:abort(400)
    with central_db() as c:c.execute('UPDATE members SET name=? WHERE code=? AND active=1',(name,member['code']))
    return jsonify(ok=True,name=name)

@midiary_bp.route('/api/language',methods=['GET','POST'])
def language():
    from routes.auth import get_personal_owner
    owner=get_personal_owner()
    if request.method=='POST':
        value=(request.get_json() or {}).get('language')
        if value not in ('ru','en','zh'):abort(400)
        central_set_setting('language_'+owner,value)
    return jsonify(language=central_setting('language_'+owner,'ru'))

@midiary_bp.get('/api/account-code')
def account_code():
    from routes.auth import get_current_member
    member=get_current_member()
    return jsonify(code=member.get('code',''))

@midiary_bp.get('/api/bots/info')
def bots_info():
    from services.max_platform import BOT_USERNAME
    username=central_setting('bot_username','SPAMSUP_bot')
    if not re.fullmatch('[a-zA-Z0-9_]{5,32}',username):abort(503)
    return jsonify(telegram='https://t.me/'+username,max='https://max.ru/'+BOT_USERNAME)

@midiary_bp.route('/api/homework-reminders',methods=['GET','POST'])
def homework_reminders():
    from routes.auth import get_current_member,get_personal_owner
    from services.homework_reminders import times,save_times,CHOICES
    member=get_current_member();owner=get_personal_owner()
    if request.method=='POST':
        try:save_times(owner,(request.get_json() or {}).get('times'))
        except ValueError:abort(400)
    from services.max_platform import user_for_owner
    return jsonify(times=times(owner),choices=CHOICES,timezone='Europe/Moscow',linked=member.get('tg') is not None or user_for_owner(owner) is not None)

@midiary_bp.route('/api/notification-channels',methods=['GET','POST'])
def notification_channels():
    from routes.auth import get_personal_owner,get_current_member
    from services.notification_channels import preferences,save
    from services.max_platform import user_for_owner
    owner=get_personal_owner();member=get_current_member()
    if request.method=='POST':
        try:save(owner,(request.get_json() or {}).get('channels'))
        except ValueError:abort(400)
    with central_db() as c:website=bool(c.execute('SELECT 1 FROM web_push_devices WHERE owner=?',(owner,)).fetchone())
    return jsonify(channels=preferences(owner),connected={'telegram':member.get('tg') is not None,'max':user_for_owner(owner) is not None,'website':website})

@midiary_bp.get('/api/study-materials')
def study_materials():
    from routes.auth import get_personal_owner
    from services.community import db
    from services.material_access import file_visible
    owner=get_personal_owner()
    with db() as c:
        files=[dict(r) for r in c.execute('SELECT * FROM files ORDER BY created DESC') if file_visible(r,owner)]
        sets={str(r['id']):dict(r) for r in c.execute('SELECT * FROM material_sets')}
        topics={str(r['id']):r['title'] for r in c.execute('SELECT * FROM topics')}
        personal=[dict(r) for r in c.execute("SELECT * FROM personal WHERE owner=? AND kind='note' ORDER BY updated DESC",(get_personal_owner(),)) if not r['item'].startswith('reader-bookmark:')]
    for file in files:
        if file['scope']=='material':file['subject']=sets.get(file['item'],{}).get('subject','');file['category']=sets.get(file['item'],{}).get('category','notes')
        elif file['scope']=='lesson':
            parts=file['item'].split('|');file['subject']=parts[3] if len(parts)>3 else file['item'];file['category']='notes'
        else:file['subject']=topics.get(file['item'],'Литература');file['category']='literature'
    return jsonify(files=files,notes=personal)

@midiary_bp.get('/api/lesson-detail')
def lesson_detail():
    from routes.auth import get_personal_owner
    from services.community import db
    from database import get_setting
    item=request.args.get('item','')
    if not item.startswith(get_setting('group_name')+'|') or len(item)>300:abort(400)
    owner=get_personal_owner()
    from services.material_access import require_item
    require_item(item,owner,lesson=True)
    from services.subgroups import lesson_items
    items=lesson_items(item);placeholders=','.join('?' for _ in items)
    with db() as c:
        files=[dict(r) for r in c.execute("SELECT * FROM files WHERE scope='lesson' AND item IN ("+placeholders+") ORDER BY created DESC",items)]
        deadline=c.execute('SELECT d.*,COALESCE(s.minutes,0) AS minutes FROM deadlines d LEFT JOIN deadline_subs s ON d.item=s.item AND s.owner=? WHERE d.item=?',(owner,item)).fetchone()
        if not deadline and len(items)>1:deadline=c.execute('SELECT d.*,COALESCE(s.minutes,0) AS minutes FROM deadlines d LEFT JOIN deadline_subs s ON d.item=s.item AND s.owner=? WHERE d.item=?',(owner,items[1])).fetchone()
    deadline=dict(deadline) if deadline else None
    if deadline:deadline['offsets']=offsets(owner,'deadline:'+deadline['item'],[deadline['minutes']] if deadline['minutes'] else [])
    return jsonify(files=files,deadline=deadline)
