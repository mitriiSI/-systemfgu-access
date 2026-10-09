"""Verified MAX mini-app login, account linking and private native downloads."""
import hashlib,hmac,json,re,secrets,time
from urllib.parse import parse_qsl
from flask import Blueprint,abort,jsonify,request,session,send_from_directory
from config import DATA_DIR,get_public_url
from database import central_db,group_context,get_db,owner_profile,current_group
from services import max_platform as platform

max_bp=Blueprint('max_app',__name__)

def verified(raw):
    try:return platform.parse_user(raw)
    except (ValueError,TypeError,KeyError,OverflowError):abort(401)

def establish_owner(owner,user_id):
    from routes.auth import establish
    member=platform.member_for_owner(owner)
    if not member:abort(403)
    return establish(tg=member['tg'],max_user_id=user_id) if member['admin'] else establish(code=member['code'],max_user_id=user_id)

def code_login(owner,raw=None):
    user_id=verified(raw) if raw is not None else None
    try:
        with central_db() as c:
            c.execute('BEGIN IMMEDIATE')
            login=c.execute("SELECT * FROM max_logins WHERE token=? AND status='approved' AND expires>?",(session.get('max_login_token',''),time.time())).fetchone()
            if user_id is None and login:user_id=login['user_id']
            if user_id is None:return establish_owner_without_max(owner)
            platform.bind(c,user_id,owner)
            if login:c.execute('DELETE FROM max_logins WHERE token=?',(login['token'],))
    except PermissionError:abort(409)
    return establish_owner(owner,user_id)

def establish_owner_without_max(owner):
    from routes.auth import establish
    return establish(tg=int(owner[6:])) if owner.startswith('admin:') else establish(code=owner[7:])

@max_bp.get('/api/max/info')
def info():
    return jsonify(configured=platform.configured(),bot_url='https://max.ru/'+platform.BOT_USERNAME,
        app_url='https://max.ru/'+platform.BOT_USERNAME+'?startapp')

@max_bp.post('/api/max/auth')
def auth():
    from routes.auth import browser_limit
    browser_limit();raw=(request.get_json() or {}).get('initData');user_id=verified(raw)
    member=platform.identity(user_id)
    if not member:
        with central_db() as c:linked=c.execute('SELECT owner FROM max_identities WHERE user_id=?',(user_id,)).fetchone()
        if linked:abort(403)
        return jsonify(needs_code=True)
    # The signed launch parameter belongs to the browser which started login.
    # The mini-app can confirm that browser without waiting for a bot message.
    start=dict(parse_qsl(raw,keep_blank_values=True)).get('start_param','')
    confirmation=None
    if re.fullmatch(r'login_[A-Za-z0-9_-]{43}',start):
        with central_db() as c:
            pending=c.execute("SELECT token FROM max_logins WHERE token=? AND status='pending' AND expires>?",(start[6:],time.time())).fetchone()
            if pending:confirmation={'token':pending['token']}
    response=establish_owner(member['owner'],user_id)
    if confirmation:return jsonify(response.get_json()|{'browser_confirmation':confirmation})
    return response

@max_bp.post('/api/max/browser/confirm')
def confirm_browser():
    user_id=session.get('max_user_id');body=request.get_json(silent=True)
    if user_id is None:abort(403)
    if not isinstance(body,dict) or type(body.get('approve')) is not bool or not isinstance(body.get('token'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',body['token']):abort(400)
    with central_db() as c:
        changed=c.execute("UPDATE max_logins SET status=?,user_id=? WHERE token=? AND status='pending' AND expires>?",('approved' if body['approve'] else 'denied',user_id,body['token'],time.time())).rowcount
    if not changed:return jsonify(error='Запрос входа истёк. Начните вход в браузере заново.'),409
    return jsonify(ok=True)

@max_bp.route('/api/max/account',methods=['GET','POST','DELETE'])
def account():
    from routes.auth import get_personal_owner
    owner=get_personal_owner()
    if request.method=='POST':
        user_id=verified((request.get_json() or {}).get('initData'))
        try:
            with central_db() as c:
                c.execute('BEGIN IMMEDIATE');platform.bind(c,user_id,owner)
        except PermissionError:abort(409)
    elif request.method=='DELETE':
        with central_db() as c:
            c.execute('DELETE FROM max_identities WHERE owner=?',(owner,));c.execute('DELETE FROM max_file_tickets WHERE owner=?',(owner,))
        session.pop('max_user_id',None)
    return jsonify(linked=bool(platform.user_for_owner(owner)),bot_url='https://max.ru/'+platform.BOT_USERNAME)

@max_bp.post('/api/max/browser/start')
def browser_start():
    from routes.auth import browser_limit
    browser_limit()
    if not platform.configured():abort(503)
    now=time.time()
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM max_logins WHERE expires<?',(now,))
        pending=c.execute("SELECT token,expires FROM max_logins WHERE token=? AND status='pending' AND expires>?",(session.get('max_login_token',''),now+10)).fetchone()
        if pending:token,expires=pending['token'],pending['expires']
        else:
            token=secrets.token_urlsafe(32);expires=now+300
            c.execute('DELETE FROM max_logins WHERE token=?',(session.get('max_login_token',''),))
            c.execute('INSERT INTO max_logins(token,expires) VALUES(?,?)',(token,expires))
    session['max_login_token']=token
    return jsonify(url='https://max.ru/'+platform.BOT_USERNAME+'?startapp=login_'+token,expires_in=max(1,int(expires-now)))

@max_bp.post('/api/max/browser/poll')
def browser_poll():
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM max_logins WHERE token=?',(session.get('max_login_token',''),)).fetchone()
        if not row or row['expires']<time.time():return jsonify(status='expired')
        if row['status']!='approved':return jsonify(status=row['status'])
        user_id=row['user_id'];member=platform.identity(user_id)
        if not member:
            if c.execute('SELECT 1 FROM max_identities WHERE user_id=?',(user_id,)).fetchone():abort(403)
            return jsonify(needs_code=True,status='needs_code')
        c.execute('DELETE FROM max_logins WHERE token=?',(row['token'],))
    return establish_owner(member['owner'],user_id)

@max_bp.post('/api/max/webhook')
def webhook():
    value=platform.credentials();secret=request.headers.get('X-Max-Bot-Api-Secret','')
    if not value['token'] or not value['secret'] or not hmac.compare_digest(secret.encode(),value['secret'].encode()):abort(403)
    if request.content_length is None or request.content_length>128*1024:abort(413)
    update=request.get_json(silent=True)
    if not isinstance(update,dict):abort(400)
    from bot.max_worker import enqueue
    try:enqueue(update)
    except (KeyError,ValueError,TypeError):abort(400)
    return jsonify(ok=True)

def file_record(ident,owner=None):
    from services.material_access import file_record as accessible_file
    if owner is None:
        from routes.auth import get_personal_owner
        owner=get_personal_owner()
    row=accessible_file(ident,owner)
    path=DATA_DIR/'files'/ident
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to((DATA_DIR/'files').resolve()):abort(404)
    return dict(row)

@max_bp.post('/api/max/files/<ident>/ticket')
def file_ticket(ident):
    from routes.auth import get_personal_owner
    file_record(ident);token=secrets.token_urlsafe(32)
    with central_db() as c:
        c.execute('DELETE FROM max_file_tickets WHERE expires<?',(time.time(),))
        c.execute('INSERT INTO max_file_tickets VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),get_personal_owner(),current_group(),ident,time.time()+300))
    return jsonify(url=get_public_url()+'/api/max/download/'+token,expires_in=300)

@max_bp.get('/api/max/download/<token>')
def native_download(token):
    if not re.fullmatch('[A-Za-z0-9_-]{43}',token):abort(404)
    with central_db() as c:row=c.execute('SELECT * FROM max_file_tickets WHERE hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if not row or not platform.member_for_owner(row['owner']):abort(403)
    profile=owner_profile(row['owner'])
    if not profile or profile['group_id']!=row['group_id']:abort(403)
    with group_context(row['group_id']):file=file_record(row['file_id'],row['owner'])
    response=send_from_directory(DATA_DIR/'files',file['id'],as_attachment=True,download_name=file['filename'],mimetype='application/octet-stream')
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response
