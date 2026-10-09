"""Diary routes restored from the original project."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from flask import Blueprint, request, jsonify, session, abort, current_app, send_from_directory
from config import BOT_TOKEN as TOKEN, ADMIN_IDS as ADMINS, get_public_url as public_url
from config import DATA_DIR as DATA, ROOT_DIR as ROOT, MOSCOW_TZ as MOSCOW
from database import central_connection as _get_db, central_setting as setting, set_setting as put_setting, utc_now as now
from services.timetable import sync_schedule
from database import owner_profile,register_telegram,select_group,reset_group,get_setting,central_db,group_record
from flask import g

@contextmanager
def db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

auth_bp = Blueprint('auth', __name__)

def parse_telegram_user(raw):
    if not isinstance(raw,str) or not 1<=len(raw)<=16384:raise ValueError('Invalid launch data')
    pairs = parse_qsl(raw, keep_blank_values=True)
    if len(dict(pairs)) != len(pairs):
        raise ValueError('Duplicate fields')
    fields = dict(pairs)
    given = fields.pop('hash', '')
    check = '\n'.join((f'{k}={v}' for k, v in sorted(fields.items())))
    key = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    if not TOKEN or not hmac.compare_digest(given, expected):
        raise ValueError('Invalid signature')
    age = time.time() - int(fields.get('auth_date', '0'))
    if not -30 <= age <= 3600:
        raise ValueError('Expired Telegram login')
    user_id=json.loads(fields['user'])['id']
    if type(user_id) is not int or not 0<user_id<2**63:raise ValueError('Invalid Telegram identity')
    return user_id

def get_current_member():
    from services.privacy import blocked
    tg = session.get('tg')
    if session.get('code'):
        with db() as c:
            r = c.execute('SELECT * FROM members WHERE code=? AND active=1', (session['code'],)).fetchone()
        if not r or blocked('member:'+r['code']):
            abort(403)
        check_max_session('member:'+r['code'])
        return dict(r) | {'admin': False, 'moderate': setting('moderate_' + r['code'], '0') == '1'}
    if not tg:
        abort(401)
    if tg in ADMINS:
        check_max_session('admin:'+str(tg))
        return {'tg': tg, 'name': 'Администратор', 'english': setting('english_' + str(tg)), 'admin': True}
    with db() as c:
        r = c.execute('SELECT * FROM members WHERE tg=? AND active=1', (tg,)).fetchone()
    if not r or blocked('member:'+r['code']):
        abort(403)
    check_max_session('member:'+r['code'])
    return dict(r) | {'admin': False, 'moderate': setting('moderate_' + r['code'], '0') == '1'}

def check_max_session(owner):
    if session.get('max_user_id') is not None:
        from services.max_platform import identity
        member=identity(session['max_user_id'])
        if not member or member['owner']!=owner:abort(403)

def get_personal_owner():
    m = get_current_member()
    return 'admin:' + str(m['tg']) if m['admin'] else 'member:' + m['code']

@auth_bp.before_app_request
def protect():
    from services.security import bound_request,owner_limit
    if request.path.startswith('/api/'):bound_request()
    public = {'/api/legal','/api/register','/api/faculties','/api/groups','/api/auth', '/api/browser/id', '/api/browser/start', '/api/browser/poll'}
    public.update({'/api/bots/info','/api/max/info','/api/max/auth','/api/max/browser/start','/api/max/browser/poll','/api/max/webhook'})
    if request.path.startswith('/api/max/download/'):public.add(request.path)
    if request.path.startswith('/api/') and request.path not in public:
        get_current_member()
        profile=owner_profile(get_personal_owner())
        if profile and profile['group_id']:g.group_token=select_group(profile['group_id'])
        elif request.path not in ('/api/legal/consent','/api/me','/api/study-group','/api/logout','/api/language','/api/account-code','/api/max/account','/api/upload-check') and not request.path.startswith(('/api/account/','/api/admin/')):return jsonify(error='Группа ещё не назначена администратором.',needs_group=True),409
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.path.startswith('/api/') and request.path != '/api/max/webhook':
        if request.headers.get('Origin') and request.headers['Origin'] != public_url():
            abort(403)
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.path not in public:
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', '').encode(), session.get('csrf', '!').encode()):
            abort(403)
    if request.path.startswith('/api/'):
        if request.method in ('POST','PUT','PATCH','DELETE') and request.is_json and not isinstance(request.get_json(),dict):abort(400)
        if request.path in ('/api/browser/poll','/api/max/browser/poll'):
            from services.security import client_address,limit
            pending=session.get('max_login_token' if request.path.startswith('/api/max/') else 'login_token','')
            limit('login-poll',client_address()+':'+pending,120,60)
        if request.path not in public:
            owner_limit(get_personal_owner())
            g.activity_owner=get_personal_owner()

@auth_bp.after_app_request
def headers(r):
    if g.get('activity_owner') and 200 <= r.status_code < 300:
        from services.user_activity import touch
        touch(g.activity_owner)
    from services.security import response_headers
    response_headers(r)
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['Referrer-Policy'] = 'no-referrer' if request.path.startswith('/api/max/download/') else 'same-origin'
    if request.path.startswith('/api/'):
        r.headers['Cache-Control'] = 'no-store'
    elif request.path == '/' or request.path.startswith(('/static/','/legal/')):
        r.headers['Cache-Control'] = 'no-cache'
    if r.is_json and not r.direct_passthrough:
        value=r.get_json(silent=True)
        if isinstance(value,dict) and isinstance(value.get('error'),str):
            from services.i18n import translate
            lang=request.headers.get('X-Midiary-Language','ru');value['error']=translate(value['error'],lang if lang in ('ru','en','zh') else 'ru');r.set_data(json.dumps(value,ensure_ascii=False));r.headers['Content-Type']='application/json'
    return r

@auth_bp.teardown_app_request
def clear_group_context(error):
    token=g.pop('group_token',None)
    if token is not None:reset_group(token)

@auth_bp.post('/api/auth')
def auth():
    browser_limit()
    raw=(request.get_json() or {}).get('initData','')
    try:
        tg=parse_telegram_user(raw)
        register_telegram({'id':tg})
    except PermissionError:
        with db() as c:row=c.execute('SELECT active FROM members WHERE tg=?',(tg,)).fetchone()
        if row:abort(403)
        return jsonify(needs_code=True)
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):abort(401)
    return establish(tg=tg)

@auth_bp.get('/api/me')
def me():
    m=get_current_member();owner=get_personal_owner();profile=owner_profile(owner) or {};faculty=profile.get('faculty');selected=bool(profile.get('group_id'))
    from services.group_comparison import allowed as private_comparison,primary as comparison_admin
    return jsonify(m|{'csrf':session['csrf'],'group':get_setting('group_name') if selected else '',
       'group_comparison':private_comparison(owner),
       'group_comparison_admin':comparison_admin(owner),
       'group_id':profile.get('group_id'),'faculty':faculty,'source':(group_record() or {}).get('source','') if selected else '',
       'needs_group':not selected,
       'choose_study_group':setting('study_choice:'+owner)=='1',
       'theme':get_setting('theme_'+owner) if selected else '',
       'language':setting('language_'+owner,'ru'),
       'onboarding_seen':setting('onboarding_v1_'+owner)=='1',
       'teacher_write':m['admin'] or get_setting('teacher_write_'+m['code'],'1')=='1'})


@auth_bp.post('/api/account/onboarding')
def onboarding_seen():
    owner=get_personal_owner()
    with central_db() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('onboarding_v1_'+owner,'1'))
    return jsonify(seen=True)


def browser_limit():
    from services.security import client_address,limit
    limit('login',client_address(),10,900)

@auth_bp.get('/api/upload-check')
def upload_check():
    # The edge performs this bodyless subrequest before accepting a large upload.
    if not (owner_profile(get_personal_owner()) or {}).get('group_id'):abort(403)
    if request.headers.get('X-Midiary-Upload-Method')=='GET':return '',204
    if request.headers.get('Origin') and request.headers['Origin'] != public_url():abort(403)
    if request.headers.get('Sec-Fetch-Site')=='cross-site':abort(403)
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token','').encode(),session.get('csrf','!').encode()):abort(403)
    return '',204

def establish(tg=None, code=None,max_user_id=None):
    session.clear()
    if tg is not None:
        session['tg'] = tg
    if code is not None:
        session['code'] = code
    if max_user_id is not None:session['max_user_id']=max_user_id
    session['csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify(ok=True, csrf=session['csrf'])

@auth_bp.post('/api/browser/id')
def browser_id():
    browser_limit()
    code = str((request.get_json() or {}).get('code', '')).strip()
    with db() as c:
        row = c.execute('SELECT code FROM members WHERE code=? AND active=1', (code,)).fetchone()
    if not row:
        digest = hmac.new(current_app.secret_key.encode(), ('admin-code:' + code).encode(), hashlib.sha256).hexdigest()
        for admin in ADMINS:
            if hmac.compare_digest(digest, setting('admin_code_' + str(admin), '!')):
                from routes.max_app import code_login
                return code_login('admin:'+str(admin),(request.get_json() or {}).get('maxInitData'))
        return (jsonify(error='Код не найден или доступ отключён. Нужен секретный ID из команды /add, а не числовой Telegram ID. Администратор задаёт свой код командой /mycode.'), 403)
    from routes.max_app import code_login
    return code_login('member:'+row['code'],(request.get_json() or {}).get('maxInitData'))

@auth_bp.post('/api/browser/start')
def browser_start():
    browser_limit()
    username=setting('bot_username')
    if not username:return jsonify(error='Бот ещё запускается. Попробуйте позже.'),503
    now=int(time.time())
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM browser_logins WHERE expires<?',(now,))
        pending=c.execute("SELECT token,expires FROM browser_logins WHERE token=? AND status='pending' AND expires>?",(session.get('login_token',''),now+10)).fetchone()
        if pending:token,expires=pending['token'],pending['expires']
        else:
            token=secrets.token_urlsafe(32);expires=now+300
            c.execute('DELETE FROM browser_logins WHERE token=?',(session.get('login_token',''),))
            c.execute('INSERT INTO browser_logins(token,expires) VALUES(?,?)',(token,expires))
    session['login_token']=token
    return jsonify(url=f'https://t.me/{username}?start=login_{token}',expires_in=max(1,int(expires-now)))

@auth_bp.post('/api/browser/poll')
def browser_poll():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM browser_logins WHERE token=?',(session.get('login_token',''),)).fetchone()
        if not row or row['expires']<time.time():return jsonify(status='expired')
        if row['status']!='approved':return jsonify(status=row['status'])
        member=c.execute('SELECT * FROM members WHERE tg=?',(row['tg'],)).fetchone()
        if member and not member['active']:abort(403)
        if row['tg'] not in ADMINS and not member:return jsonify(needs_code=True,status='needs_code')
        c.execute('DELETE FROM browser_logins WHERE token=?',(row['token'],))
    return establish(tg=row['tg'])

@auth_bp.post('/api/logout')
def logout():
    from services.webpush import unsubscribe
    ident=(request.get_json() or {}).get('push_device')
    if isinstance(ident,str) and len(ident)==64:unsubscribe(get_personal_owner(),ident)
    session.clear()
    return jsonify(ok=True)
