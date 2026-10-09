"""Separate Telegram support inbox with encrypted credentials and durable delivery."""
import base64
import hashlib
import json
import os
import re
import threading
import time

import requests
from cryptography.fernet import Fernet
from flask import Blueprint, abort, jsonify, request

from config import ADMIN_IDS, BOT_TOKEN, SESSION_SECRET
from database import central_db, central_setting, central_set_setting

support_bp = Blueprint('support', __name__)
USERNAME = 'midiarybot'


class SupportAPIError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Support Telegram API error: ' + str(code))


def cipher():
    key = hashlib.sha256(('Midiary support:' + SESSION_SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(value):
    return cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def unseal(value):
    return json.loads(cipher().decrypt(value.encode()))


def initialize():
    with central_db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS support_queue(
            bot_id INTEGER,update_id INTEGER,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0,created REAL NOT NULL,
            header_id INTEGER,copied_id INTEGER,PRIMARY KEY(bot_id,update_id));
        CREATE TABLE IF NOT EXISTS support_replies(
            bot_id INTEGER,admin INTEGER,message_id INTEGER,user_id INTEGER NOT NULL,original_id INTEGER NOT NULL,
            created REAL NOT NULL,PRIMARY KEY(bot_id,admin,message_id));
        ''')


def configuration():
    encrypted = central_setting('support_token')
    token = unseal(encrypted) if encrypted else os.getenv('SUPPORT_BOT_TOKEN', '')
    recipient = int(central_setting('support_recipient', str(min(ADMIN_IDS)) if ADMIN_IDS else '0'))
    enabled = central_setting('support_enabled', '1' if token else '0') == '1'
    return token, recipient, enabled


def call(token, method, **data):
    response = requests.post('https://api.telegram.org/bot' + token + '/' + method, json=data, timeout=35)
    try:
        value = response.json()
    except ValueError:
        raise SupportAPIError(response.status_code) from None
    if response.status_code >= 400 or not value.get('ok'):
        raise SupportAPIError(value.get('error_code', response.status_code))
    return value['result']


def validate_token(token):
    if not isinstance(token, str) or not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{30,100}', token):
        raise ValueError('Проверьте токен бота поддержки.')
    if BOT_TOKEN and token.split(':')[0] == BOT_TOKEN.split(':')[0]:
        raise ValueError('Для поддержки нужен отдельный бот @midiarybot.')
    info = call(token, 'getMe')
    if not info.get('is_bot') or str(info.get('username', '')).casefold() != USERNAME:
        raise ValueError('Этот токен принадлежит другому боту. Нужен @midiarybot.')
    return info['id']


def public_status():
    initialize()
    token, recipient, enabled = configuration()
    try:
        health = json.loads(central_setting('support_health', '{}'))
    except ValueError:
        health = {}
    bot_id = int(central_setting('support_bot_id', '0'))
    with central_db() as c:
        counts = dict(c.execute('SELECT state,count(*) FROM support_queue WHERE bot_id=? GROUP BY state', (bot_id,)).fetchall())
    return {'username': USERNAME, 'configured': bool(token), 'enabled': enabled, 'recipient': recipient,
            'recipients': sorted(ADMIN_IDS), 'pending': counts.get('pending', 0), 'failed': counts.get('failed', 0),
            'last_poll_at': health.get('last_poll_at'), 'last_delivery_at': health.get('last_delivery_at'),
            'last_error': health.get('last_error', '')}


@support_bp.route('/api/admin/support', methods=['GET', 'POST'])
def settings():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:
        abort(403)
    if request.method == 'POST':
        body = request.get_json() or {}
        if body.get('retry') is True:
            initialize()
            bot_id=int(central_setting('support_bot_id','0'))
            with central_db() as c:c.execute("UPDATE support_queue SET state='pending',next_at=0 WHERE bot_id=? AND state='failed'",(bot_id,))
        elif body.get('enabled') is False:
            central_set_setting('support_enabled', '0')
        else:
            recipient = body.get('recipient')
            if type(recipient) is not int or recipient not in ADMIN_IDS:
                abort(400)
            token = body.get('token') or configuration()[0]
            try:
                bot_id = validate_token(token)
                # Preserve pending messages when switching the dedicated bot to polling.
                call(token, 'deleteWebhook', drop_pending_updates=False)
            except ValueError as error:
                return jsonify(error=str(error)), 400
            except Exception:
                return jsonify(error='Не удалось подключить Telegram. Проверьте токен и повторите попытку.'), 502
            with central_db() as c:
                for key, value in (('support_token', seal(token)), ('support_recipient', str(recipient)),
                                   ('support_enabled', '1'), ('support_bot_id', str(bot_id)), ('support_health', '{}')):
                    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, value))
    return jsonify(public_status())


def enqueue(bot_id, update, recipient):
    """Commit the message and update offset together before calling Telegram."""
    initialize()
    message = update.get('message', {})
    payload = None
    if message.get('chat', {}).get('type') == 'private' and message.get('from', {}).get('id') == message['chat']['id']:
        sender = message['from']['id']
        text = message.get('text', '')
        if sender in ADMIN_IDS:
            replied = message.get('reply_to_message', {}).get('message_id')
            with central_db() as c:
                row = c.execute('SELECT user_id,original_id FROM support_replies WHERE bot_id=? AND admin=? AND message_id=?', (bot_id, sender, replied)).fetchone()
            if row:
                payload = {'kind': 'reply', 'source': sender, 'message': message['message_id'], 'target': row['user_id'], 'original': row['original_id']}
        elif text.split(maxsplit=1)[0:1] not in (['/start'], ['/help'], ['/myid']):
            user = message['from']
            name = ' '.join(str(user.get(k) or '') for k in ('first_name', 'last_name')).strip()[:200]
            payload = {'kind': 'incoming', 'source': sender, 'message': message['message_id'], 'target': recipient,
                       'name': name, 'username': str(user.get('username') or '')[:32]}
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if payload:
            c.execute('INSERT OR IGNORE INTO support_queue(bot_id,update_id,payload,created) VALUES(?,?,?,?)', (bot_id, update['update_id'], seal(payload), time.time()))
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('support_offset:' + str(bot_id), str(update['update_id'] + 1)))
    return payload is not None


def remember_reply(c, bot_id, payload, message_id):
    c.execute('INSERT OR REPLACE INTO support_replies VALUES(?,?,?,?,?,?)', (bot_id, payload['target'], message_id, payload['source'], payload['message'], time.time()))


def deliver_pending(token, bot_id, health):
    initialize()
    with central_db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM support_queue WHERE bot_id=? AND state='pending' AND next_at<=? ORDER BY update_id LIMIT 20", (bot_id, time.time()))]
    for row in rows:
        payload = unseal(row['payload'])
        try:
            if payload['kind'] == 'incoming' and row['header_id'] is None:
                username = ' @' + payload['username'] if payload['username'] else ''
                header = call(token, 'sendMessage', chat_id=payload['target'],
                              text='Обращение в поддержку\n' + payload['name'] + username + '\nTelegram ID: ' + str(payload['source']) + '\nОтветьте на это сообщение или на вложение, чтобы ответить человеку.')
                row['header_id'] = header['message_id']
                with central_db() as c:
                    c.execute('UPDATE support_queue SET header_id=? WHERE bot_id=? AND update_id=?', (row['header_id'], bot_id, row['update_id']))
                    remember_reply(c, bot_id, payload, row['header_id'])
            if row['copied_id'] is None:
                data = {'chat_id': payload['target'], 'from_chat_id': payload['source'], 'message_id': payload['message']}
                original = row['header_id'] if payload['kind'] == 'incoming' else payload['original']
                data['reply_parameters'] = {'message_id': original, 'allow_sending_without_reply': True}
                copied = call(token, 'copyMessage', **data)
                row['copied_id'] = copied['message_id']
                with central_db() as c:
                    c.execute('UPDATE support_queue SET copied_id=? WHERE bot_id=? AND update_id=?', (row['copied_id'], bot_id, row['update_id']))
                    if payload['kind'] == 'incoming':
                        remember_reply(c, bot_id, payload, row['copied_id'])
            acknowledgement = 'Обращение доставлено владельцу Midiary. Ответ придёт сюда.' if payload['kind'] == 'incoming' else 'Ответ доставлен.'
            call(token, 'sendMessage', chat_id=payload['source'], text=acknowledgement)
            with central_db() as c:
                c.execute("UPDATE support_queue SET state='delivered' WHERE bot_id=? AND update_id=?", (bot_id, row['update_id']))
            health['last_delivery_at'] = time.time()
        except Exception as error:
            status = getattr(error, 'code', None)
            permanent = status in (400, 403)
            with central_db() as c:
                c.execute('UPDATE support_queue SET state=?,attempts=attempts+1,next_at=? WHERE bot_id=? AND update_id=?',
                          ('failed' if permanent else 'pending', time.time() + min(300, 5 * 2 ** min(row['attempts'], 6)), bot_id, row['update_id']))
            health['last_error'] = 'Telegram ' + str(status) if status else type(error).__name__
    with central_db() as c:
        c.execute("DELETE FROM support_queue WHERE state<>'pending' AND created<?", (time.time() - 30 * 86400,))
        c.execute('DELETE FROM support_replies WHERE created<?', (time.time() - 30 * 86400,))
    central_set_setting('support_health', json.dumps(health))


def poll_once(token, recipient, bot_id, health):
    offset = int(central_setting('support_offset:' + str(bot_id), '0'))
    updates = call(token, 'getUpdates', offset=offset, timeout=20, allowed_updates=['message'])
    health['last_poll_at'] = time.time()
    health['last_error'] = ''
    for update in updates:
        if update['update_id'] < offset:
            continue
        message = update.get('message', {})
        if not enqueue(bot_id, update, recipient) and message.get('chat', {}).get('type') == 'private':
            sender = message['chat']['id']
            text = message.get('text', '').split(maxsplit=1)[0:1]
            if text == ['/myid']:
                reply = str(sender)
            elif sender in ADMIN_IDS:
                reply = 'Ответьте на сообщение с обращением, чтобы отправить ответ человеку.'
            else:
                reply = 'Поддержка Midiary. Напишите вопрос или отправьте фото, документ, голосовое сообщение. Обращение будет передано владельцу сервиса.'
            call(token, 'sendMessage', chat_id=sender, text=reply)
        offset = update['update_id'] + 1
    deliver_pending(token, bot_id, health)


def start_worker(stop):
    def loop():
        validated = None
        health = {}
        while not stop.is_set():
            try:
                token, recipient, enabled = configuration()
                if not token or not enabled or recipient not in ADMIN_IDS:
                    stop.wait(5)
                    continue
                if token != validated:
                    bot_id = validate_token(token)
                    central_set_setting('support_bot_id', bot_id)
                    validated = token
                deliver_pending(token, bot_id, health)
                poll_once(token, recipient, bot_id, health)
            except Exception as error:
                # URLs, tokens and message text must never enter logs or health responses.
                health['last_error'] = 'Telegram ' + str(error.code) if isinstance(error, SupportAPIError) else type(error).__name__
                central_set_setting('support_health', json.dumps(health))
                stop.wait(5)
    threading.Thread(target=loop, daemon=True, name='SupportTelegram').start()
