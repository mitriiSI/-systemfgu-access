"""Translate displayed text asynchronously on a private, local LibreTranslate service.

Original database values and downloadable files are never replaced.
"""
import hashlib,json,re,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse
from flask import Blueprint,request,jsonify,abort
from config import DATA_DIR
from database import central_db

translation_bp=Blueprint('content_translation',__name__)
executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='midiary-translation')
lock=threading.Lock();pending=set();attempts={}

def configuration():
    try:
        value=json.loads((DATA_DIR/'midiary-translation.json').read_text())
        url=value['url'];parsed=urlparse(url)
        if parsed.hostname!='midiary-translate' or parsed.scheme!='http' or parsed.port!=5000:return None
        return url.rstrip('/')
    except (OSError,ValueError,KeyError):return None

def initialize():
    with central_db() as c:c.execute('CREATE TABLE IF NOT EXISTS midiary_text_translations(owner TEXT,key TEXT,language TEXT,text TEXT,created REAL,PRIMARY KEY(owner,key,language))')

def translate_batch(texts,language,timeout=45):
    url=configuration()
    if not url:return None
    body=json.dumps({'q':texts,'source':'auto','target':language,'format':'text'}).encode()
    with urlopen(Request(url+'/translate',data=body,headers={'Content-Type':'application/json'}),timeout=timeout) as response:result=json.load(response)['translatedText']
    if not isinstance(result,list) or len(result)!=len(texts) or any(not isinstance(x,str) for x in result):raise ValueError('Invalid translation response')
    return result

def notification_text(text,language):
    if language=='ru' or not re.search('[А-Яа-яЁё]',text) or len(text)>4000 or not configuration():return text
    initialize();key=hashlib.sha256(text.encode()).hexdigest()
    with central_db() as c:row=c.execute("SELECT text FROM midiary_text_translations WHERE owner='notification' AND key=? AND language=?",(key,language)).fetchone()
    if row:return row[0]
    try:
        value=translate_batch([text],language,timeout=4)[0]
        with central_db() as c:c.execute('INSERT OR REPLACE INTO midiary_text_translations VALUES(?,?,?,?,?)',('notification',key,language,value,time.time()))
        return value
    except Exception:return text

def worker(owner,language,records):
    keys=[(owner,key,language) for key,_ in records]
    try:
        values=translate_batch([text for _,text in records],language)
        if values:
            with central_db() as c:
                c.executemany('INSERT OR REPLACE INTO midiary_text_translations VALUES(?,?,?,?,?)',[(owner,key,language,value,time.time()) for (key,_),value in zip(records,values)])
    except Exception:
        with lock:
            for key in keys:attempts[key]=time.time()+60
    finally:
        with lock:pending.difference_update(keys)

@translation_bp.post('/api/translate-titles')
def translate_titles():
    from routes.auth import get_personal_owner
    body=request.get_json() or {};language=body.get('language');texts=body.get('texts')
    if language not in ('ru','en','zh') or not isinstance(texts,list) or len(texts)>24 or any(not isinstance(x,str) or len(x)>4000 for x in texts) or sum(map(len,texts))>12000:abort(400)
    if language=='ru':return jsonify(translations=texts,pending=False,available=True)
    owner=get_personal_owner();initialize();records=[(hashlib.sha256(text.encode()).hexdigest(),text) for text in texts];results=[];missing=[]
    with central_db() as c:
        for key,text in records:
            row=c.execute('SELECT text FROM midiary_text_translations WHERE owner=? AND key=? AND language=?',(owner,key,language)).fetchone()
            results.append(row[0] if row else None)
            if not row:missing.append((key,text))
    available=bool(configuration());queued=[]
    if available:
        with lock:
            # Bound the total queue so a user cannot crowd out other requests.
            for key,text in dict(missing).items():
                identity=(owner,key,language)
                if len(pending)<96 and identity not in pending and attempts.get(identity,0)<=time.time():pending.add(identity);queued.append((key,text))
        if queued:executor.submit(worker,owner,language,queued)
    return jsonify(translations=results,pending=available and bool(missing),available=available)
