"""Dedicated channel publisher with encrypted settings and a durable outbox."""
import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import requests
from cryptography.fernet import Fernet
from flask import Blueprint, abort, jsonify, request

from config import ADMIN_IDS, BOT_TOKEN, ROOT_DIR, SESSION_SECRET
from database import central_db, central_setting, central_set_setting

bridge_bp = Blueprint('channel_bridge', __name__)
_worker_lock = threading.Lock()
_configuration_lock = threading.RLock()
_wake = threading.Event()
_started = False
DEFAULTS = {'enabled': False, 'automatic_updates': True, 'forward_messages': True,
            'telegram_token': '', 'telegram_channel': '', 'max_token': '', 'max_channel': ''}


class BridgeAPIError(RuntimeError):
    def __init__(self, platform, status):
        self.platform, self.status = platform, status
        super().__init__('Channel API status ' + str(status))


def initialize():
    with central_db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS channel_posts(
            id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_deliveries(
            post TEXT NOT NULL,platform TEXT NOT NULL,part INTEGER NOT NULL,target TEXT NOT NULL,
            identity TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
            next_at REAL NOT NULL DEFAULT 0,sent_at REAL,error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(post,platform,part));
        CREATE INDEX IF NOT EXISTS channel_delivery_state ON channel_deliveries(state,next_at);
        ''')


def cipher():
    key = hashlib.sha256(('Midiary channel bridge:' + SESSION_SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def configuration():
    encrypted = central_setting('channel_bridge_configuration')
    value = json.loads(cipher().decrypt(encrypted.encode())) if encrypted else {}
    return DEFAULTS | value


def identity(config, platform):
    return hashlib.sha256(config[platform+'_token'].encode()).hexdigest()


def release():
    value = json.loads((ROOT_DIR / 'release.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}', value['version']):
        raise ValueError('Invalid release identifier')
    if not isinstance(value['text'], str) or not 1 <= len(value['text']) <= 24000:
        raise ValueError('Invalid release notes')
    return value


def chunks(text):
    """Both APIs count astral characters conservatively as UTF-16 units."""
    result, current, units = [], [], 0
    for char in text:
        size = 2 if ord(char) > 0xffff else 1
        if units+size > 3500:
            result.append(''.join(current)); current, units = [], 0
        current.append(char); units += size
    if current:
        result.append(''.join(current))
    return result


def enqueue_in(c, key, kind, title, text, platforms, config):
    c.execute('INSERT OR IGNORE INTO channel_posts VALUES(?,?,?,?,?)', (key, kind, title, text, time.time()))
    for platform in platforms:
        for part, _ in enumerate(chunks(text)):
            c.execute('''INSERT OR IGNORE INTO channel_deliveries(post,platform,part,target,identity)
                VALUES(?,?,?,?,?)''', (key, platform, part, config[platform+'_channel'], identity(config, platform)))


def enqueue_release(config):
    if not config['enabled'] or not config['automatic_updates']:
        return
    current = release()
    with central_db() as c:
        enqueue_in(c, 'release:'+current['version'], 'release', 'Обновление '+current['version'],
                   current['text'], ('telegram', 'max'), config)


def validate(body, current):
    if not isinstance(body, dict):
        raise ValueError('Проверьте настройки.')
    result = dict(current)
    for key in ('enabled', 'automatic_updates', 'forward_messages'):
        if key in body:
            if type(body[key]) is not bool:
                raise ValueError('Проверьте переключатели отправки.')
            result[key] = body[key]
    for platform in ('telegram', 'max'):
        for suffix in ('token', 'channel'):
            key = platform+'_'+suffix
            if key in body:
                value = body[key]
                if not isinstance(value, str) or len(value) > 300:
                    raise ValueError('Проверьте токен и канал '+platform+'.')
                # Empty password fields keep the token already stored on the server.
                if suffix == 'channel' or value.strip():
                    result[key] = value.strip()
    token = result['telegram_token']
    if token and not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{30,100}', token):
        raise ValueError('Проверьте токен Telegram из BotFather.')
    from services.support import configuration as support_configuration
    occupied = [BOT_TOKEN, support_configuration()[0]]
    if token and any(other and token.split(':')[0] == other.split(':')[0] for other in occupied):
        raise ValueError('Для каналов нужен отдельный Telegram-бот. Создайте его через BotFather.')
    channel = result['telegram_channel']
    if channel and not (re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}', channel) or
                        re.fullmatch(r'-100[0-9]{5,16}', channel)):
        raise ValueError('Канал Telegram: @имя_канала или ID, начинающийся с -100.')
    token = result['max_token']
    if token and not re.fullmatch(r'[A-Za-z0-9_.:\-]{20,300}', token):
        raise ValueError('Проверьте токен бота MAX.')
    channel = result['max_channel']
    if channel and (not re.fullmatch(r'-?[0-9]{1,19}', channel) or not -2**63 < int(channel) < 2**63 or int(channel) == 0):
        raise ValueError('Укажите числовой chat_id канала MAX.')
    if result['enabled'] and not all(result[p+'_'+s] for p in ('telegram', 'max') for s in ('token', 'channel')):
        raise ValueError('Для включения укажите оба токена и оба канала.')
    return result


def safe_error(error):
    if isinstance(error, BridgeAPIError):
        status = error.status
        if status == 401:
            return 'Токен не принят. Проверьте настройки.'
        if status == 403:
            return 'Нет права публикации. Добавьте бота администратором канала.'
        if status == 409:
            return 'Этот Telegram-бот уже подключён к другому обработчику или webhook.'
        if status == 429:
            return 'Лимит отправки. Повторим позже.'
        return 'API '+error.platform+': ошибка '+str(status)+'. Проверьте токен, канал и права бота.'
    return 'Нет подтверждения от сервиса. Проверьте канал перед повторной отправкой.'


def telegram_call(config, method, **payload):
    if method not in ('getUpdates', 'sendMessage'):
        raise ValueError('Unsupported Telegram method')
    response = requests.post('https://api.telegram.org/bot'+config['telegram_token']+'/'+method,
                             json=payload, timeout=(8, 25), allow_redirects=False)
    try:
        value = response.json()
    except ValueError:
        raise BridgeAPIError('Telegram', response.status_code) from None
    if response.status_code != 200 or not isinstance(value, dict) or value.get('ok') is not True:
        code = value.get('error_code', response.status_code) if isinstance(value, dict) else response.status_code
        raise BridgeAPIError('Telegram', code if type(code) is int else response.status_code)
    return value.get('result')


def max_send(config, target, text):
    from services.network_trust import certificate_bundle
    ca = str(Path(__file__).with_name('max_root_ca.pem'))
    response = requests.post('https://platform-api2.max.ru/messages',
        headers={'Authorization': config['max_token']}, params={'chat_id': int(target), 'disable_link_preview': True},
        json={'text': text, 'notify': True}, timeout=(8, 25), verify=certificate_bundle(ca), allow_redirects=False)
    try:
        value = response.json()
    except ValueError:
        raise BridgeAPIError('MAX', response.status_code) from None
    if response.status_code != 200 or not isinstance(value, dict) or not isinstance(value.get('message'), dict):
        raise BridgeAPIError('MAX', response.status_code)
    return value


def public_status():
    config = configuration()
    with central_db() as c:
        history = []
        for post in c.execute('SELECT id,kind,title,created FROM channel_posts ORDER BY created DESC LIMIT 30'):
            deliveries = [dict(row) for row in c.execute('''SELECT platform,part,target,state,attempts,sent_at,error
                FROM channel_deliveries WHERE post=? ORDER BY platform,part''', (post['id'],))]
            history.append({'id': post['id'], 'kind': post['kind'], 'title': post['title'], 'created': post['created'], 'deliveries': deliveries})
    try:
        health = json.loads(central_setting('channel_bridge_health', '{}'))
    except ValueError:
        health = {}
    return {'enabled': config['enabled'], 'automatic_updates': config['automatic_updates'],
            'forward_messages': config['forward_messages'],
            'telegram_configured': bool(config['telegram_token']), 'max_configured': bool(config['max_token']),
            'telegram_channel': config['telegram_channel'], 'max_channel': config['max_channel'],
            'release': release(), 'history': history, 'health': health}


@bridge_bp.route('/api/admin/channel-bridge', methods=['GET', 'POST'])
def settings():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:
        abort(403)
    if request.method == 'POST':
        with _configuration_lock:
            try:
                value = validate(request.get_json(), configuration())
            except ValueError as error:
                return jsonify(error=str(error)), 400
            sealed = cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()
            central_set_setting('channel_bridge_configuration', sealed)
            enqueue_release(value)
            _wake.set()
    return jsonify(public_status())


@bridge_bp.post('/api/admin/channel-bridge/retry')
def retry():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:
        abort(403)
    with _configuration_lock:
        config = configuration()
        if not config['enabled']:
            return jsonify(error='Сначала подключите и включите бота.'), 400
        with central_db() as c:
            for platform in ('telegram', 'max'):
                c.execute('''UPDATE channel_deliveries SET state='pending',attempts=0,next_at=0,error=''
                    WHERE state IN ('failed','uncertain') AND platform=? AND target=? AND identity=?''',
                    (platform, config[platform+'_channel'], identity(config, platform)))
        _wake.set()
    return jsonify(public_status())


def accept_updates(config, updates):
    """Persist each accepted message and polling offset in the same transaction."""
    if not config['enabled'] or not isinstance(updates, list):
        return
    bot = config['telegram_token'].split(':')[0]
    with central_db() as c:
        for update in updates:
            if not isinstance(update, dict) or type(update.get('update_id')) is not int:
                continue
            message = update.get('message', {})
            sender, chat = message.get('from', {}), message.get('chat', {})
            text = message.get('text')
            if (config['forward_messages'] and chat.get('type') == 'private' and
                sender.get('id') in ADMIN_IDS and chat.get('id') == sender.get('id') and
                sender.get('is_bot') is not True and isinstance(text, str) and
                0 < len(text) <= 24000 and not text.startswith('/')):
                enqueue_in(c, 'telegram:'+bot+':'+str(update['update_id']), 'message',
                           'Сообщение из Telegram', text, ('max',), config)
            key = 'channel_bridge_offset:'+bot
            row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            offset = max(int(row[0]) if row else 0, update['update_id']+1)
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, str(offset)))


def deliver_one():
    with _configuration_lock:
        config = configuration()
        if not config['enabled']:
            return False
        with central_db() as c:
            c.execute('BEGIN IMMEDIATE')
            # Sending after a crash has an unknown outcome; require an explicit retry.
            c.execute("UPDATE channel_deliveries SET state='uncertain',error=? WHERE state='sending' AND next_at<?",
                      ('Отправка прервалась. Проверьте канал перед повторной отправкой.', time.time()))
            rows = c.execute('''SELECT d.*,p.body FROM channel_deliveries d JOIN channel_posts p ON p.id=d.post
                WHERE d.state='pending' AND d.next_at<=? AND NOT EXISTS(
                    SELECT 1 FROM channel_deliveries earlier WHERE earlier.post=d.post AND earlier.platform=d.platform
                    AND earlier.part<d.part AND earlier.state!='sent') ORDER BY p.created,d.platform,d.part''', (time.time(),)).fetchall()
            job = next((dict(row) for row in rows if row['target'] == config[row['platform']+'_channel'] and
                        row['identity'] == identity(config, row['platform'])), None)
            if not job:
                return False
            c.execute("UPDATE channel_deliveries SET state='sending',attempts=attempts+1,next_at=? WHERE post=? AND platform=? AND part=?",
                      (time.time()+90, job['post'], job['platform'], job['part']))
    error, state, retry_at = '', 'sent', 0
    try:
        text = chunks(job['body'])[job['part']]
        if job['platform'] == 'telegram':
            telegram_call(config, 'sendMessage', chat_id=job['target'], text=text,
                          link_preview_options={'is_disabled': True})
        else:
            max_send(config, job['target'], text)
    except Exception as exc:
        error = safe_error(exc)
        known_rejection = isinstance(exc, BridgeAPIError) and 400 <= exc.status < 500
        state = 'failed' if known_rejection else 'uncertain'
        if isinstance(exc, BridgeAPIError) and exc.status == 429 and job['attempts'] < 7:
            state, retry_at = 'pending', time.time()+max(60, 2**(job['attempts']+1))
    with central_db() as c:
        c.execute('''UPDATE channel_deliveries SET state=?,next_at=?,sent_at=?,error=?
            WHERE post=? AND platform=? AND part=?''',
            (state, retry_at, time.time() if state == 'sent' else None, error, job['post'], job['platform'], job['part']))
    return True


def poll_once(config):
    with _configuration_lock:
        if not config['enabled'] or not config['forward_messages'] or configuration() != config:
            return
        key = 'channel_bridge_offset:'+config['telegram_token'].split(':')[0]
        offset = int(central_setting(key, '0'))
    updates = telegram_call(config, 'getUpdates', offset=offset, timeout=10, limit=50, allowed_updates=['message'])
    with _configuration_lock:
        current = configuration()
        if current == config:
            accept_updates(current, updates)
            for update in updates or []:
                message = update.get('message', {})
                sender, chat = message.get('from', {}), message.get('chat', {})
                if (chat.get('type') == 'private' and sender.get('id') in ADMIN_IDS and
                    chat.get('id') == sender.get('id') and message.get('text') in ('/start', '/help')):
                    telegram_call(config, 'sendMessage', chat_id=sender['id'],
                        text='Напишите сюда текст — он будет опубликован в подключённом канале MAX. '
                             'Обновления сервиса публикуются в Telegram и MAX автоматически. '
                             'Настройки и история отправок: профиль Midiary → Обновления и каналы.')


def run(stop):
    while not stop.is_set():
        try:
            with _configuration_lock:
                config = configuration()
                enqueue_release(config)
            if not config['enabled']:
                _wake.wait(5); _wake.clear(); continue
            for _ in range(12):
                if stop.is_set() or not deliver_one():
                    break
                if stop.wait(.55):
                    return
            poll_once(config)
            central_set_setting('channel_bridge_health', json.dumps({'last_check': time.time(), 'error': ''}))
            stop.wait(1)
        except Exception as exc:
            central_set_setting('channel_bridge_health', json.dumps({'last_check': time.time(), 'error': safe_error(exc)}))
            stop.wait(20)


def start_worker(stop):
    global _started
    with _worker_lock:
        if _started:
            return
        initialize()
        _started = True
        threading.Thread(target=run, args=(stop,), daemon=True, name='ChannelPublisher').start()
