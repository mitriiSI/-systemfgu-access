"""Administrator admissions; all consumption happens inside the account transaction."""
import hashlib
import hmac
import secrets
import time

from config import ADMIN_IDS, SESSION_SECRET
from database import central_db, group_record, initialize_group, utc_now

DEFAULT_GROUP = 'fgu:1457'
MAX_USES = 10000


def invitation_hash(code):
    return hmac.new(SESSION_SECRET.encode(), ('midiary-invite:' + code).encode(), hashlib.sha256).hexdigest()


def initialize():
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS midiary_invites(hash TEXT PRIMARY KEY,creator TEXT NOT NULL,expires REAL NOT NULL,used_by TEXT,created REAL NOT NULL)')
        columns = {r[1] for r in c.execute('PRAGMA table_info(midiary_invites)')}
        for name, declaration in (
            ('guardian_version', "TEXT NOT NULL DEFAULT ''"),
            ('max_uses', 'INTEGER NOT NULL DEFAULT 1'),
            ('uses', 'INTEGER NOT NULL DEFAULT 0'),
            ('revoked', 'INTEGER NOT NULL DEFAULT 0'),
            ('group_id', "TEXT NOT NULL DEFAULT 'fgu:1457'"),
        ):
            if name not in columns:
                c.execute('ALTER TABLE midiary_invites ADD COLUMN ' + name + ' ' + declaration)
        if 'uses' not in columns:
            c.execute('UPDATE midiary_invites SET uses=1 WHERE used_by IS NOT NULL')
        c.execute('CREATE TABLE IF NOT EXISTS midiary_invite_uses(invite_hash TEXT,owner TEXT,used_at REAL NOT NULL,PRIMARY KEY(invite_hash,owner))')
        c.execute('INSERT OR IGNORE INTO midiary_invite_uses SELECT hash,used_by,created FROM midiary_invites WHERE used_by IS NOT NULL')
        c.execute('''CREATE TABLE IF NOT EXISTS telegram_registration_grants(
            tg INTEGER PRIMARY KEY,creator TEXT NOT NULL,expires REAL NOT NULL,used_by TEXT,
            created REAL NOT NULL,guardian_version TEXT NOT NULL,group_id TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)''')


def administrator(owner):
    if not isinstance(owner, str) or not owner.startswith('admin:') or owner[6:] not in {str(x) for x in ADMIN_IDS}:
        raise PermissionError('Administrator required')


def quota(value):
    if type(value) is not int or not 1 <= value <= MAX_USES:
        raise ValueError('Количество регистраций должно быть от 1 до 10000.')
    return value


def telegram_id(value):
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or not 1 <= value < 2 ** 63:
        raise ValueError('Укажите числовой Telegram ID. Его можно узнать командой /myid.')
    return value


def admission_group(key=DEFAULT_GROUP):
    if not isinstance(key, str) or not group_record(key):
        raise ValueError('Группа не найдена.')
    initialize_group(key)
    return key


def guardian_version(guardian):
    if type(guardian) is not bool:
        raise ValueError('Проверьте возрастную категорию.')
    if guardian:
        from services.legal import ready, archive
        if not ready():
            raise ValueError('Сведения о владельце сервиса не заполнены.')
        return archive()
    return ''


def create_invitation(owner, guardian=False, count=1, group_id=DEFAULT_GROUP):
    administrator(owner)
    count = quota(count)
    group_id = admission_group(group_id)
    version = guardian_version(guardian)
    initialize()
    code = secrets.token_urlsafe(18)
    stamp = time.time()
    with central_db() as c:
        c.execute('''INSERT INTO midiary_invites(hash,creator,expires,created,guardian_version,max_uses,group_id)
            VALUES(?,?,?,?,?,?,?)''', (invitation_hash(code), owner, stamp + 7 * 86400, stamp, version, count, group_id))
    from services.timetable import start_sync
    start_sync(group_id)
    return code


def allow_telegram(owner, tg, guardian=False, group_id=DEFAULT_GROUP):
    administrator(owner)
    tg = telegram_id(tg)
    group_id = admission_group(group_id)
    version = guardian_version(guardian)
    initialize()
    stamp = time.time()
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if tg in ADMIN_IDS or c.execute('SELECT 1 FROM members WHERE tg=?', (tg,)).fetchone():
            raise ValueError('Этот Telegram ID уже связан с аккаунтом. Группу можно изменить в списке участников.')
        c.execute('''INSERT INTO telegram_registration_grants(tg,creator,expires,created,guardian_version,group_id)
            VALUES(?,?,?,?,?,?) ON CONFLICT(tg) DO UPDATE SET creator=excluded.creator,expires=excluded.expires,
            created=excluded.created,guardian_version=excluded.guardian_version,group_id=excluded.group_id,used_by=NULL,revoked=0''',
            (tg, owner, stamp + 7 * 86400, stamp, version, group_id))
    from services.timetable import start_sync
    start_sync(group_id)
    return tg


def available_grant(tg):
    initialize()
    with central_db() as c:
        return bool(c.execute('SELECT 1 FROM telegram_registration_grants WHERE tg=? AND used_by IS NULL AND revoked=0 AND expires>?', (tg, time.time())).fetchone())


def invitation(c, code, owner=None):
    if not isinstance(code, str) or not 10 <= len(code.strip()) <= 100:
        raise ValueError('Введите действующий код приглашения администратора.')
    row = c.execute('SELECT * FROM midiary_invites WHERE hash=?', (invitation_hash(code.strip()),)).fetchone()
    already = row and owner and c.execute('SELECT 1 FROM midiary_invite_uses WHERE invite_hash=? AND owner=?', (row['hash'], owner)).fetchone()
    if not row or row['revoked'] or row['expires'] <= time.time() or (row['uses'] >= row['max_uses'] and not already):
        raise ValueError('Код приглашения недействителен, отозван или его лимит исчерпан.')
    return row


def consume_invitation(c, row, owner):
    if c.execute('SELECT 1 FROM midiary_invite_uses WHERE invite_hash=? AND owner=?', (row['hash'], owner)).fetchone():
        return
    changed = c.execute('''UPDATE midiary_invites SET uses=uses+1,used_by=COALESCE(used_by,?)
        WHERE hash=? AND revoked=0 AND expires>? AND uses<max_uses''', (owner, row['hash'], time.time())).rowcount
    if not changed:
        raise ValueError('Лимит приглашения исчерпан.')
    c.execute('INSERT INTO midiary_invite_uses VALUES(?,?,?)', (row['hash'], owner, time.time()))


def consume(c, owner, *, code='', tg=None, minor=False, consent=''):
    if code:
        row = invitation(c, code)
        kind = 'invite'
    else:
        row = c.execute('SELECT * FROM telegram_registration_grants WHERE tg=?', (tg,)).fetchone() if tg else None
        if not row or row['revoked'] or row['used_by'] or row['expires'] <= time.time():
            raise ValueError('Нужен код приглашения или разрешение администратора для вашего Telegram ID.')
        kind = 'telegram'
    if minor and row['guardian_version'] != consent:
        raise ValueError('Для участника младше 18 лет нужен специальный доступ после подтверждения представителя.')
    if not c.execute('SELECT 1 FROM university_groups WHERE id=?', (row['group_id'],)).fetchone():
        raise ValueError('Назначенная группа не найдена. Обратитесь к администратору.')
    if kind == 'invite':
        consume_invitation(c, row, owner)
    else:
        c.execute('UPDATE telegram_registration_grants SET used_by=? WHERE tg=?', (owner, tg))
    return row['group_id']


def set_profile(c, owner, group_id):
    record = c.execute('SELECT faculty FROM university_groups WHERE id=?', (group_id,)).fetchone()
    if not record:
        raise ValueError('Группа не найдена.')
    c.execute('''INSERT INTO university_profiles VALUES(?,?,?,?) ON CONFLICT(owner)
        DO UPDATE SET faculty=excluded.faculty,group_id=excluded.group_id''', (owner, record['faculty'], group_id, utc_now()))


def assign_member(owner, code, group_id):
    administrator(owner)
    group_id = admission_group(group_id)
    with central_db() as c:
        if not c.execute('SELECT 1 FROM members WHERE code=?', (code,)).fetchone():
            raise ValueError('Участник не найден.')
        set_profile(c, 'member:' + code, group_id)
    # Commit the assignment before the worker opens the group's database.
    from services.timetable import start_sync
    start_sync(group_id)


def status(row, invite=False):
    if row['revoked']:
        return 'revoked'
    if row['expires'] <= time.time():
        return 'expired'
    exhausted = row['uses'] >= row['max_uses'] if invite else bool(row['used_by'])
    if exhausted:
        return 'used'
    return 'active'


def overview():
    initialize()
    with central_db() as c:
        invites = [{ 'id': r['hash'], 'created': r['created'], 'expires': r['expires'], 'count': r['max_uses'],
            'used': r['uses'], 'remaining': max(0, r['max_uses'] - r['uses']), 'group_id': r['group_id'],
            'minor': bool(r['guardian_version']), 'status': status(r, True)}
            for r in c.execute('SELECT * FROM midiary_invites ORDER BY created DESC LIMIT 100')]
        grants = [{'id': r['tg'], 'expires': r['expires'], 'group_id': r['group_id'],
            'minor': bool(r['guardian_version']), 'status': status(r)}
            for r in c.execute('SELECT * FROM telegram_registration_grants ORDER BY created DESC LIMIT 100')]
    return {'invites': invites, 'telegram': grants}


def revoke(owner, kind, key):
    administrator(owner)
    initialize()
    if kind not in ('invite', 'telegram'):
        raise ValueError('Неизвестный вид доступа.')
    table, field = ('midiary_invites', 'hash') if kind == 'invite' else ('telegram_registration_grants', 'tg')
    if kind == 'telegram':
        key = telegram_id(key)
    elif not isinstance(key, str) or len(key) != 64:
        raise ValueError('Приглашение не найдено.')
    with central_db() as c:
        if not c.execute('UPDATE ' + table + ' SET revoked=1 WHERE ' + field + '=?', (key,)).rowcount:
            raise ValueError('Разрешение не найдено.')
