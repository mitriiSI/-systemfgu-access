"""Shared identity directory with isolated SQLite storage for each study group."""
import sqlite3,json,hashlib,secrets,contextvars,sys
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
from config import DATA_DIR,ADMIN_IDS

VENDOR=Path(__file__).resolve().parent/'vendor'/'webpush'
if VENDOR.is_dir():sys.path.insert(0,str(VENDOR))

DB_PATH=DATA_DIR/'diary.sqlite3'
SCHEMA="\n        PRAGMA journal_mode = WAL;\n\n        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS members (code TEXT PRIMARY KEY, name TEXT NOT NULL, tg INTEGER UNIQUE, active INTEGER DEFAULT 1, english TEXT DEFAULT '');\n        CREATE TABLE IF NOT EXISTS schedules (group_id TEXT, day TEXT, body TEXT, PRIMARY KEY(group_id, day));\n        CREATE TABLE IF NOT EXISTS content (kind TEXT, item TEXT, body TEXT, author TEXT, updated TEXT, PRIMARY KEY(kind, item));\n        CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, item TEXT, body TEXT, author TEXT, updated TEXT);\n        CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, item TEXT, body TEXT, author TEXT, status TEXT DEFAULT 'pending');\n        CREATE TABLE IF NOT EXISTS topics (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT UNIQUE NOT NULL);\n        CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, scope TEXT, item TEXT, title TEXT, filename TEXT, author TEXT, created TEXT, size INTEGER);\n        CREATE TABLE IF NOT EXISTS attempts (tg INTEGER PRIMARY KEY, count INTEGER, until INTEGER);\n        CREATE TABLE IF NOT EXISTS browser_logins (token TEXT PRIMARY KEY, expires INTEGER, tg INTEGER, status TEXT DEFAULT 'pending');\n        CREATE TABLE IF NOT EXISTS web_attempts (key TEXT PRIMARY KEY, count INTEGER, until INTEGER);\n        CREATE TABLE IF NOT EXISTS reminder_prefs (owner TEXT PRIMARY KEY, minutes INTEGER NOT NULL);\n        CREATE TABLE IF NOT EXISTS reminder_delivery (owner TEXT, lesson TEXT, attempts INTEGER, next_at REAL, PRIMARY KEY(owner, lesson));\n        CREATE TABLE IF NOT EXISTS reminder_sent (owner TEXT, lesson TEXT, sent_at TEXT, PRIMARY KEY(owner, lesson));\n        CREATE TABLE IF NOT EXISTS personal (owner TEXT, kind TEXT, item TEXT, body TEXT, updated TEXT, PRIMARY KEY(owner, kind, item));\n        CREATE TABLE IF NOT EXISTS material_sets (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS deadlines (item TEXT PRIMARY KEY, group_name TEXT NOT NULL, title TEXT NOT NULL, due TEXT NOT NULL, updated TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS deadline_subs (owner TEXT NOT NULL, item TEXT NOT NULL, minutes INTEGER NOT NULL, PRIMARY KEY(owner, item));\n        \n\n        CREATE TABLE IF NOT EXISTS hidden_lessons(owner TEXT,group_id TEXT,lesson_id TEXT,created TEXT,PRIMARY KEY(owner,group_id,lesson_id));\n        CREATE TABLE IF NOT EXISTS custom_lessons(id TEXT PRIMARY KEY,owner TEXT,group_id TEXT,body TEXT,active INTEGER NOT NULL DEFAULT 1);\n        CREATE TABLE IF NOT EXISTS teacher_reviews(id TEXT PRIMARY KEY,teacher TEXT NOT NULL,owner TEXT NOT NULL,author TEXT NOT NULL,\n          clarity INTEGER NOT NULL,knowledge INTEGER NOT NULL,communication INTEGER NOT NULL,recommend INTEGER NOT NULL,\n          comment TEXT NOT NULL,public_author INTEGER NOT NULL,updated TEXT NOT NULL,UNIQUE(teacher,owner));\n        CREATE INDEX IF NOT EXISTS custom_lessons_owner ON custom_lessons(group_id,owner,active);\n        CREATE INDEX IF NOT EXISTS teacher_reviews_teacher ON teacher_reviews(teacher);\n        \n\n    CREATE TABLE IF NOT EXISTS web_push_devices(id TEXT PRIMARY KEY,owner TEXT NOT NULL,subscription TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);\n    CREATE INDEX IF NOT EXISTS web_push_owner ON web_push_devices(owner);\n    CREATE TABLE IF NOT EXISTS web_push_preferences(owner TEXT PRIMARY KEY,lessons INTEGER NOT NULL DEFAULT 1,deadlines INTEGER NOT NULL DEFAULT 1,lesson_minutes INTEGER NOT NULL DEFAULT 0,deadline_minutes INTEGER NOT NULL DEFAULT 60);\n    CREATE TABLE IF NOT EXISTS web_push_deliveries(device TEXT,event TEXT,state TEXT NOT NULL,attempts INTEGER NOT NULL,next_at REAL NOT NULL,sent_at REAL,PRIMARY KEY(device,event));\n    \nCREATE TABLE IF NOT EXISTS schedule_imports(id TEXT PRIMARY KEY,owner TEXT,created REAL,expires REAL,payload TEXT,filename TEXT,committed INTEGER DEFAULT 0,added INTEGER DEFAULT 0);\n"
_selected=contextvars.ContextVar('diary_group',default=None)

def connect(path):
    c=sqlite3.connect(path,timeout=30);c.row_factory=sqlite3.Row;return c

@contextmanager
def central_db():
    c=connect(DB_PATH)
    try:
        with c:yield c
    finally:c.close()

def central_setting(key,default=''):
    with central_db() as c:row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return row[0] if row else default

def central_set_setting(key,value):
    with central_db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,str(value)))

def default_group():return central_setting('university_default_group','fgu:'+central_setting('group_id','1457'))
def current_group():return _selected.get() or default_group()
def select_group(key):return _selected.set(key)
def reset_group(token):_selected.reset(token)

@contextmanager
def group_context(key):
    token=select_group(key)
    try:yield
    finally:reset_group(token)

def group_record(key=None):
    with central_db() as c:row=c.execute('SELECT * FROM university_groups WHERE id=?',(key or current_group(),)).fetchone()
    return dict(row) if row else None

def current_faculty():return (group_record() or {}).get('faculty','fgu')

def group_path(key):
    if key==default_group():return DB_PATH
    return DB_PATH.parent/'groups'/(hashlib.sha256(key.encode()).hexdigest()+'.sqlite3')

def central_connection():return connect(DB_PATH)

def get_db():return connect(group_path(current_group()))
def utc_now():return datetime.now(timezone.utc).isoformat()

def get_setting(key,default=''):
    c=get_db()
    try:row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return row[0] if row else default
    finally:c.close()

def set_setting(key,value):
    c=get_db()
    try:
        with c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,str(value)))
    finally:c.close()

def initialize_group(key):
    group=group_record(key)
    if not group:raise ValueError('Unknown study group')
    path=group_path(key);path.parent.mkdir(parents=True,exist_ok=True)
    c=connect(path)
    try:
        with c:
            c.executescript(SCHEMA)
            c.execute("INSERT OR IGNORE INTO settings VALUES('group_id',?)",(group['source_id'] or key,))
            c.execute("INSERT OR IGNORE INTO settings VALUES('group_name',?)",(group['name'],))
            c.execute("INSERT OR IGNORE INTO topics(title) VALUES('Общее')")
    finally:c.close()
    return path

def owner_profile(owner):
    with central_db() as c:row=c.execute('SELECT * FROM university_profiles WHERE owner=?',(owner,)).fetchone()
    return dict(row) if row else None

def group_members(key=None):
    key=key or current_group()
    with central_db() as c:
        rows=list(c.execute("SELECT m.* FROM members m JOIN university_profiles p ON p.owner='member:'||m.code WHERE p.group_id=? AND m.active=1",(key,)))
    return [dict(r) for r in rows]

def group_admins(key=None):
    key=key or current_group()
    with central_db() as c:rows={r[0] for r in c.execute('SELECT owner FROM university_profiles WHERE group_id=?',(key,))}
    return {int(tg) for tg in ADMIN_IDS if 'admin:'+str(tg) in rows}

def active_groups():
    with central_db() as c:return [r[0] for r in c.execute('SELECT DISTINCT group_id FROM university_profiles WHERE group_id IS NOT NULL')]

def register_telegram(user):
    tg=user.get('id')
    if type(tg) is not int or tg<=0:raise ValueError('Invalid Telegram identity')
    if tg in ADMIN_IDS:return 'admin:'+str(tg)
    name=' '.join(str(user.get(key) or '').strip() for key in ('first_name','last_name')).strip()[:200] or 'Участник'
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM members WHERE tg=?',(tg,)).fetchone()
        if row:
            if not row['active']:raise PermissionError('Access revoked')
            return 'member:'+row['code']
        raise PermissionError('Registration requires an administrator invitation')


def seed_catalogs():
    root=Path(__file__).resolve().parent/'catalog'
    try:groups=json.loads((root/'fgu-groups.json').read_text(encoding='utf-8'));teachers=json.loads((root/'fgu-teachers.json').read_text(encoding='utf-8'));levels={r['id']:r['name'] for r in json.loads((root/'fgu-education-levels.json').read_text(encoding='utf-8'))}
    except (FileNotFoundError,ValueError):return
    with central_db() as c:
        for row in groups:
            c.execute('INSERT INTO university_groups VALUES(?,?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET name=excluded.name,level=excluded.level,course=excluded.course',('fgu:'+str(row['id']),'fgu',str(row['id']),row['name'],levels.get(row['education_level_id'],''),int(row.get('course') or 0),'fgu'))
        for row in teachers:
            name=row.get('full_name','').strip()
            if name:c.execute('INSERT INTO faculty_teachers VALUES(?,?,?,?,?) ON CONFLICT(faculty,name) DO UPDATE SET short_name=excluded.short_name,external_id=excluded.external_id',('fgu',name,row.get('short_name',''),str(row['id']),'Мой ФГУ'))

def upsert_external_groups(rows):
    with central_db() as c:
        for row in rows:
            legacy = c.execute('''SELECT id FROM university_groups WHERE faculty='geo' AND source='excel'
                AND name=? AND level=? AND course=? LIMIT 1''',
                (row['name'],row['level'],row['course'])).fetchone() if row['faculty']=='geo' else None
            key = legacy['id'] if legacy else row['id']
            c.execute('''INSERT INTO university_groups(id,faculty,source_id,name,level,course,source,creator)
                VALUES(?,?,?,?,?,?,?,NULL)
                ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id,name=excluded.name,
                level=excluded.level,course=excluded.course,source=excluded.source''',
                (key,row['faculty'],row['source_id'],row['name'],row['level'],row['course'],row['source']))
            c.execute('INSERT OR REPLACE INTO university_group_programs VALUES(?,?)',(key,row.get('program','')))

def init_db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with central_db() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO settings VALUES('group_id','1457')")
        c.execute("INSERT OR IGNORE INTO settings VALUES('group_name','107пб')")
        c.execute("INSERT OR IGNORE INTO topics(title) VALUES('Общее')")
        c.executescript('''
        CREATE TABLE IF NOT EXISTS university_groups(id TEXT PRIMARY KEY,faculty TEXT NOT NULL,source_id TEXT,name TEXT NOT NULL,level TEXT NOT NULL,course INTEGER NOT NULL,source TEXT NOT NULL,creator TEXT);
        CREATE TABLE IF NOT EXISTS university_group_programs(group_id TEXT PRIMARY KEY,program TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS university_profiles(owner TEXT PRIMARY KEY,faculty TEXT,group_id TEXT,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS faculty_teachers(faculty TEXT,name TEXT,short_name TEXT,external_id TEXT,source TEXT,PRIMARY KEY(faculty,name));
        CREATE TABLE IF NOT EXISTS faculty_reviews(id TEXT UNIQUE,faculty TEXT NOT NULL,teacher TEXT NOT NULL,owner TEXT NOT NULL,author TEXT NOT NULL,clarity INTEGER NOT NULL,knowledge INTEGER NOT NULL,communication INTEGER NOT NULL,recommend INTEGER NOT NULL,comment TEXT NOT NULL,public_author INTEGER NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(faculty,teacher,owner));
        ''')
        group=c.execute("SELECT value FROM settings WHERE key='group_id'").fetchone()[0];name=c.execute("SELECT value FROM settings WHERE key='group_name'").fetchone()[0];key='fgu:'+group
        c.execute("INSERT OR IGNORE INTO settings VALUES('university_default_group',?)",(key,))
        c.execute('INSERT OR IGNORE INTO university_groups VALUES(?,?,?,?,?,?,?,NULL)',(key,'fgu',group,name,'Бакалавриат',1,'fgu'))
        migrated=c.execute("SELECT value FROM settings WHERE key='university_migrated'").fetchone()
        if not migrated:
            for row in c.execute('SELECT code FROM members').fetchall():c.execute('INSERT OR IGNORE INTO university_profiles VALUES(?,?,?,?)',('member:'+row['code'],'fgu',key,utc_now()))
            for tg in ADMIN_IDS:c.execute('INSERT OR IGNORE INTO university_profiles VALUES(?,?,?,?)',('admin:'+str(tg),'fgu',key,utc_now()))
            c.execute("INSERT OR IGNORE INTO faculty_reviews SELECT id,'fgu',teacher,owner,author,clarity,knowledge,communication,recommend,comment,public_author,updated FROM teacher_reviews")
            c.execute("INSERT INTO settings VALUES('university_migrated','1')")
    seed_catalogs()
    seed_manual_catalogs()
    with central_db() as c:
        # Assign an initial group only; preserve every later administrator assignment.
        for row in c.execute('SELECT code FROM members').fetchall():
            c.execute("INSERT OR IGNORE INTO university_profiles VALUES(?,'fgu','fgu:1457',?)",('member:'+row['code'],utc_now()))
        c.execute("UPDATE university_profiles SET faculty='fgu',group_id='fgu:1457' WHERE group_id IS NULL")

def seed_manual_catalogs():
    root=Path(__file__).resolve().parent/'catalog'
    for faculty in ('ffl','fgp'):
        try:rows=json.loads((root/(faculty+'-groups.json')).read_text(encoding='utf-8'))
        except (FileNotFoundError,ValueError):continue
        upsert_external_groups(rows)

