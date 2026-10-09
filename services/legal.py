"""Public documents with real operator details, separate consent and guardian invitations."""
import hashlib,json,re
from flask import Blueprint,abort,jsonify,render_template,request
from database import central_db,central_setting,central_set_setting,utc_now
from config import ROOT_DIR

legal_bp=Blueprint('legal',__name__)
VERSION='2026-10-04'
FIELDS=('operator','contact','address','hosting_country','hosting_provider')
DEFAULT_OPERATOR='Плотников Дмитрий Евгеньевич'
DEFAULT_SETTINGS={'operator':DEFAULT_OPERATOR,'contact':'@midiarybot','hosting_country':'Финляндия'}

def settings():
    try:value=json.loads(central_setting('privacy_operator','{}'))
    except ValueError:value={}
    if not isinstance(value,dict):value={}
    result={key:str(value.get(key,DEFAULT_SETTINGS.get(key,''))).strip() for key in FIELDS}
    if not result['operator']:result['operator']=DEFAULT_OPERATOR
    return result

def ready():
    value=settings();return bool(value['operator'] and value['contact'] and value['hosting_country'])

def contact_href(value):
    if re.fullmatch(r'@?[a-zA-Z][a-zA-Z0-9_]{4,31}',value):return 'https://t.me/'+value.lstrip('@')
    if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):return 'mailto:'+value
    return ''

def catalogue():return json.loads((ROOT_DIR/'static/legal-texts.json').read_text(encoding='utf-8'))

def snapshot():return {'version':VERSION,'operator':settings(),'documents':catalogue()}
def fingerprint(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def version():return fingerprint(snapshot())

def archive(data=None):
    from services.privacy import initialize
    initialize();data=data or snapshot();body=json.dumps(data,ensure_ascii=False,sort_keys=True);v=fingerprint(data)
    with central_db() as c:c.execute('INSERT OR IGNORE INTO privacy_documents VALUES(?,?,?)',(v,body,utc_now()))
    return v

def registration_consent(body):
    data=snapshot()
    if not all(data['operator'][key] for key in ('operator','contact','hosting_country')):abort(503,description='Operator details not configured')
    if body.get('terms_accepted') is not True or body.get('privacy_accepted') is not True or body.get('age_group') not in ('adult','minor') or body.get('legal_version')!=fingerprint(data):abort(400)
    return archive(data)

@legal_bp.get('/api/legal')
def public_info():return jsonify(operator=settings(),ready=ready(),version=version(),guardian_required=True)

@legal_bp.route('/api/admin/legal',methods=['GET','POST'])
def configure():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:abort(403)
    if request.method=='POST':
        body=request.get_json() or {};value={}
        for key in FIELDS:
            text=body.get(key,'')
            if not isinstance(text,str) or len(text)>300:abort(400)
            value[key]=' '.join(text.split())
        if not value['operator'] or not value['hosting_country']:abort(400)
        if not (re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value['contact']) or re.fullmatch(r'@?[a-zA-Z][a-zA-Z0-9_]{4,31}',value['contact'])):abort(400)
        central_set_setting('privacy_operator',json.dumps(value,ensure_ascii=False))
    return public_info()

@legal_bp.get('/legal/<document>')
def document(document):
    if document not in ('privacy','terms','cookies','consent','guardian','about','licenses','copyright'):abort(404)
    language=request.args.get('lang','ru');language=language if language in ('ru','en','zh') else 'ru'
    texts=catalogue();operator=settings();
    if language!='ru':
        from services.i18n import translate,transliterate_name
        operator['operator']=transliterate_name(operator['operator'])
        operator['hosting_country']=translate(operator['hosting_country'],language)
    return render_template('legal.html',language=language,copy=texts[language],document=texts[language]['documents'][document],key=document,operator=operator,contact_href=contact_href(operator['contact']),configured=ready(),date=VERSION)

@legal_bp.get('/robots.txt')
def robots():return 'User-agent: *\nDisallow: /api/\nDisallow: /static/vendor/\n',200,{'Content-Type':'text/plain; charset=utf-8'}

@legal_bp.route('/api/legal/consent',methods=['GET','POST'])
def first_visit_consent():
    from routes.auth import get_personal_owner
    from services.privacy import record_consent
    owner=get_personal_owner();current=version()
    if request.method=='POST':
        body=request.get_json() or {};accepted=registration_consent(body)
        from services.midiary import invitation_hash,initialize
        initialize()
        with central_db() as c:
            c.execute('BEGIN IMMEDIATE')
            if accepted!=version():abort(400)
            if body['age_group']=='minor' and not c.execute("SELECT 1 FROM privacy_consents WHERE owner=? AND kind='guardian' AND version=?",(owner,accepted)).fetchone():
                code=body.get('guardian_code','')
                if not isinstance(code,str):abort(400)
                from services.admissions import invitation,consume_invitation
                try:
                    row=invitation(c,code,owner)
                    if row['guardian_version']!=accepted:raise ValueError()
                    consume_invitation(c,row,owner)
                except ValueError:return jsonify(error='Для участника младше 18 лет нужен специальный код после подтверждения представителя.'),403
            record_consent(c,owner,'terms',accepted);record_consent(c,owner,'guardian' if body['age_group']=='minor' else 'privacy',accepted);record_consent(c,owner,'site',accepted)
    with central_db() as c:
        required=not c.execute("SELECT 1 FROM privacy_consents WHERE owner=? AND kind='site' AND version=?",(owner,current)).fetchone()
        guardian=bool(c.execute("SELECT 1 FROM privacy_consents WHERE owner=? AND kind='guardian' AND version=?",(owner,current)).fetchone())
    return jsonify(required=required,guardian_confirmed=guardian,version=current,ready=ready())
