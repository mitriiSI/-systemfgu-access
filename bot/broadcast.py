"""Persistent administrator broadcasts, delivered independently of polling."""
import threading
import time
from contextlib import contextmanager
from config import ADMIN_IDS
from database import central_connection as get_db
from services.telegram import tg_call

_started = False
_lock = threading.Lock()

@contextmanager
def connection():
    db = get_db()
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    with connection() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS broadcasts(
                id INTEGER PRIMARY KEY, admin INTEGER NOT NULL, message_id INTEGER NOT NULL,
                body TEXT NOT NULL, created REAL NOT NULL, unlinked INTEGER NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0, UNIQUE(admin,message_id));
            CREATE TABLE IF NOT EXISTS broadcast_deliveries(
                job INTEGER NOT NULL, tg INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                recipient_owner TEXT,
                PRIMARY KEY(job,tg));
        ''')
        if 'recipient_owner' not in {r['name'] for r in db.execute('PRAGMA table_info(broadcast_deliveries)')}:
            db.execute('ALTER TABLE broadcast_deliveries ADD COLUMN recipient_owner TEXT')
        db.execute("UPDATE broadcast_deliveries SET recipient_owner=(SELECT 'member:'||code FROM members WHERE members.tg=broadcast_deliveries.tg LIMIT 1) WHERE recipient_owner IS NULL AND status='queued'")

def summary(job):
    with connection() as db:
        record = db.execute('SELECT * FROM broadcasts WHERE id=?', (job,)).fetchone()
        counts = dict(db.execute('SELECT status,count(*) FROM broadcast_deliveries WHERE job=? GROUP BY status', (job,)))
    if record is None:
        return 'Рассылка не найдена.'
    pending = counts.get('queued', 0) + counts.get('sending', 0)
    return (f'Рассылка #{job}: ' + ('в процессе' if pending else 'завершена')
            + f"\nДоставлено: {counts.get('sent', 0)}"
            + f"\nОжидают: {pending}"
            + f"\nНедоступны: {counts.get('failed', 0)}"
            + f"\nДоставка не подтверждена: {counts.get('unknown', 0)}"
            + f"\nДоступ отключён: {counts.get('skipped', 0)}"
            + f"\nНе привязали Telegram: {record['unlinked']}")

def handle(message, text, status_only=False):
    admin = message.get('from', {}).get('id')
    if (admin not in ADMIN_IDS or message.get('chat', {}).get('type') != 'private'
            or message.get('chat', {}).get('id') != admin):
        return
    initialize()
    from services.max_platform import initialize as initialize_max
    from services.announcements import queue,paired_summary
    initialize_max()
    if status_only:
        with connection() as db:
            row = db.execute('SELECT id FROM broadcasts WHERE admin=? ORDER BY id DESC LIMIT 1', (admin,)).fetchone()
            max_row=db.execute('SELECT id FROM max_broadcasts WHERE owner=? ORDER BY id DESC LIMIT 1',('admin:'+str(admin),)).fetchone()
        reply = paired_summary(row['id'],max_row['id']) if row and max_row else summary(row['id']) if row else 'Рассылок пока нет. Команда: /broadcast Текст объявления'
    elif not text.strip():
        reply = 'Напиши: /broadcast Текст объявления\nСообщение получат активные участники в подключённых Telegram и MAX. Статус: /broadcast_status'
    elif len(text.encode('utf-16-le')) // 2 > 3600:
        reply = 'Сократи объявление до 3600 символов. Эмодзи могут занимать два символа.'
    elif not isinstance(message.get('message_id'), int):
        reply = 'Не удалось определить сообщение. Отправь команду заново.'
    else:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            job,max_job=queue(db,'admin:'+str(admin),'telegram',message['message_id'],text.strip())
        reply = 'Объявление поставлено в очередь.\n' + paired_summary(job,max_job) + '\nПроверить: /broadcast_status'
    tg_call('sendMessage', chat_id=admin, text=reply)

def deliver_one():
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT d.*,b.body,b.admin FROM broadcast_deliveries d
            JOIN broadcasts b ON b.id=d.job WHERE d.status='queued' AND d.retry_at<=?
            ORDER BY d.job,d.tg LIMIT 1''', (time.time(),)).fetchone()
        if row is None:
            return False
        from services.privacy import accepts_announcements
        active = accepts_announcements(row['tg'])
        member=db.execute('SELECT code FROM members WHERE tg=?',(row['tg'],)).fetchone()
        if not active or not member or row['recipient_owner']!='member:'+member['code'] or row['admin'] not in ADMIN_IDS:
            db.execute("UPDATE broadcast_deliveries SET status='skipped' WHERE job=? AND tg=?", (row['job'], row['tg']))
            return True
        db.execute("UPDATE broadcast_deliveries SET status='sending',attempts=attempts+1 WHERE job=? AND tg=?", (row['job'], row['tg']))
    status, retry_at = 'sent', 0
    try:
        from services.i18n import translate,owner_language
        with connection() as db:member=db.execute('SELECT code FROM members WHERE tg=?',(row['tg'],)).fetchone()
        footer=translate('Общие объявления можно отключить: /unsubscribe',owner_language('member:'+member['code']))
        tg_call('sendMessage', chat_id=row['tg'], text=row['body']+'\n\n'+footer,_midiary_user_content=True)
    except Exception as error:
        code = getattr(error, 'code', None)
        if code == 429 and row['attempts'] < 3:
            status = 'queued'
            retry_at = time.time() + max(1, min(getattr(error, 'retry_after', 60) or 60, 3600))
        elif code in (400, 401, 403, 404, 429):
            status = 'failed'
        else:
            # Telegram has no sendMessage idempotency key. Avoid duplicate delivery
            # when a timeout or a server failure leaves the outcome uncertain.
            status = 'unknown'
    with connection() as db:
        db.execute('UPDATE broadcast_deliveries SET status=?,retry_at=? WHERE job=? AND tg=?',
                   (status, retry_at, row['job'], row['tg']))
        if retry_at:
            # Respect a flood limit across the whole queue, not just one recipient.
            db.execute("UPDATE broadcast_deliveries SET retry_at=MAX(retry_at,?) WHERE status='queued'", (retry_at,))
    return True

def notify_completed():
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT id,admin FROM broadcasts b WHERE notified=0 AND NOT EXISTS
            (SELECT 1 FROM broadcast_deliveries d WHERE d.job=b.id AND d.status IN ('queued','sending'))
            ORDER BY id LIMIT 1''').fetchone()
        if row is None:
            return
        # /broadcast_status remains available if the summary response is lost.
        db.execute('UPDATE broadcasts SET notified=1 WHERE id=?', (row['id'],))
    if row['admin'] in ADMIN_IDS:
        tg_call('sendMessage', chat_id=row['admin'], text=summary(row['id']))

def start_worker(stop):
    global _started
    with _lock:
        if _started:
            return
        initialize()
        with connection() as db:
            db.execute("UPDATE broadcast_deliveries SET status='unknown' WHERE status='sending'")
        _started = True
    def run():
        while not stop.is_set():
            try:
                active = deliver_one()
                notify_completed()
                stop.wait(.1 if active else 1)
            except Exception as error:
                print('Broadcast worker: ' + type(error).__name__, flush=True)
                stop.wait(5)
    threading.Thread(target=run, daemon=True, name='BroadcastWorker').start()
