from database import get_db as _get_db
from contextlib import contextmanager
from services.telegram import tg_call

@contextmanager
def get_db():
    connection = _get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def send_reliable_message(owner: str, key: str, payload: dict, at_time,channel='telegram') -> None:
    from services.privacy import blocked
    if blocked(owner):return
    if channel not in ('telegram','max'):raise ValueError('Invalid reminder channel')
    from services.notification_channels import enabled
    if not enabled(owner,channel):return
    if channel=='max':
        from database import central_setting
        if central_setting('max_delivery_disabled:'+owner,'0')=='1':return
        key='max:'+key
    now_ts = at_time.timestamp()
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM reminder_sent WHERE owner = ? AND lesson = ?', (owner, key)).fetchone():
            return

        row = conn.execute('SELECT attempts, next_at FROM reminder_delivery WHERE owner = ? AND lesson = ?', (owner, key)).fetchone()
        if row and (row['attempts'] >= 3 or row['next_at'] > now_ts):
            return

        attempts = (row['attempts'] if row else 0) + 1
        conn.execute('INSERT OR REPLACE INTO reminder_delivery VALUES(?, ?, ?, ?)', (owner, key, attempts, now_ts + 180))

    try:
        if channel=='max':
            from services.max_platform import send_telegram
            send_telegram('sendMessage',payload,user_id=payload['chat_id'],owner=owner)
        else:tg_call('sendMessage', **payload)
    except Exception as exc:
        err_msg = str(exc).lower()
        permanent = ('blocked' in err_msg or 'chat not found' in err_msg)
        delay = 60 * attempts
        with get_db() as conn:
            conn.execute(
                'UPDATE reminder_delivery SET attempts = ?, next_at = ? WHERE owner = ? AND lesson = ?',
                (3 if permanent else attempts, now_ts + delay, owner, key)
            )
        print(f"Ошибка доставки сообщения: {type(exc).__name__}", flush=True)
        return

    with get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO reminder_sent VALUES(?, ?, ?)', (owner, key, at_time.isoformat()))
        conn.execute('DELETE FROM reminder_delivery WHERE owner = ? AND lesson = ?', (owner, key))
