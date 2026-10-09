"""Admission, identity, group permissions and support delivery with isolated data."""
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

TEST_DATA = tempfile.TemporaryDirectory(prefix='midiary-access-test-')
os.environ['DATA_DIR'] = TEST_DATA.name
os.environ['SESSION_SECRET'] = 'isolated-midiary-access-test-secret'
os.environ['BOT_TOKEN'] = ''
os.environ['SUPPORT_BOT_TOKEN'] = ''

from config import ADMIN_IDS
from database import central_db, init_db, owner_profile, utc_now

init_db()
from app import create_app
from services import admissions, bot_registration, support
from services.legal import version
from services.privacy import process_one


class AccessFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.admin_id = min(ADMIN_IDS)
        cls.admin_owner = 'admin:' + str(cls.admin_id)

    def setUp(self):
        sync=patch('services.timetable.start_sync',return_value=False)
        self.sync_queue=sync.start();self.addCleanup(sync.stop)
        refresh=patch('routes.schedule.start_sync',return_value=False)
        self.refresh_queue=refresh.start();self.addCleanup(refresh.stop)
        with central_db() as c:
            for table in ('midiary_invites', 'midiary_invite_uses', 'telegram_registration_grants',
                          'members', 'privacy_consents', 'bot_registrations', 'browser_logins', 'web_attempts',
                          'max_identities', 'support_queue', 'support_replies'):
                c.execute('DELETE FROM ' + table)
            c.execute("DELETE FROM university_profiles WHERE owner LIKE 'member:%'")
            c.execute("DELETE FROM settings WHERE key LIKE 'support_%'")
            c.execute("INSERT OR REPLACE INTO university_groups VALUES('fgu:99991','fgu','99991','Другая тестовая группа','Бакалавриат',1,'fgu',NULL)")
            admissions.set_profile(c, self.admin_owner, admissions.DEFAULT_GROUP)
            c.execute("INSERT INTO members(code,name) VALUES('existing-member','Старое имя')")
            admissions.set_profile(c, 'member:existing-member', admissions.DEFAULT_GROUP)
        self.admin = self.client(tg=self.admin_id)
        self.member = self.client(code='existing-member')

    def client(self, tg=None, code=None):
        client = self.app.test_client()
        with client.session_transaction() as s:
            if tg is not None:
                s['tg'] = tg
            if code:
                s['code'] = code
            s['csrf'] = 'test-csrf'
        return client

    def post(self, client, path, body):
        return client.post('/api/' + path, json=body, headers={'X-CSRF-Token': 'test-csrf'})

    def register(self, code='', client=None, **extra):
        body = {'name': 'Новый участник', 'code': code, 'terms_accepted': True, 'privacy_accepted': True,
                'age_group': 'adult', 'legal_version': version()}
        body.update(extra)
        return (client or self.app.test_client()).post('/api/register', json=body)

    def approved_client(self, tg):
        client = self.app.test_client()
        token = 'login-' + str(tg)
        with central_db() as c:
            c.execute('INSERT OR REPLACE INTO browser_logins VALUES(?,?,?,?)', (token, time.time() + 300, tg, 'approved'))
        with client.session_transaction() as s:
            s['login_token'] = token
        return client

    def code(self, **options):
        return admissions.create_invitation(self.admin_owner, **options)

    def bot_state(self, code='', **extra):
        state = {'invite': code, 'name': 'Участник из бота', 'terms': True, 'privacy': True,
                 'version': version(), 'age': 'adult', 'language': 'ru'}
        state.update(extra)
        return state


class AdminAccessTests(AccessFixture):
    def test_code_limit_and_automatic_default_group(self):
        created = self.post(self.admin, 'admin/invites', {'count': 2})
        self.assertEqual(created.status_code, 200)
        code = created.get_json()['code']
        for _ in range(2):
            client = self.app.test_client()
            self.assertEqual(self.register(code, client).status_code, 200)
            me = client.get('/api/me').get_json()
            self.assertEqual(me['group_id'], admissions.DEFAULT_GROUP)
            self.assertFalse(me['needs_group'])
        self.assertEqual(self.register(code).status_code, 403)
        state = self.admin.get('/api/admin/admissions').get_json()['invites'][0]
        self.assertEqual((state['used'], state['remaining']), (2, 0))
        self.assertNotIn('code', state)

    def test_last_slot_cannot_be_consumed_twice_concurrently(self):
        code = self.code()
        with ThreadPoolExecutor(max_workers=2) as workers:
            statuses = list(workers.map(lambda _: self.register(code).status_code, range(2)))
        self.assertEqual(sorted(statuses), [200, 403])

    def test_quota_is_shared_by_web_telegram_and_max(self):
        code = self.code(count=3)
        bot_registration.create_account('telegram', 800001, self.bot_state(code))
        bot_registration.create_account('max', 800002, self.bot_state(code))
        self.assertEqual(self.register(code).status_code, 200)
        with self.assertRaises(ValueError):
            bot_registration.create_account('telegram', 800003, self.bot_state(code))

    def test_revoked_and_expired_codes_deny_registration(self):
        code = self.code(count=2)
        self.assertEqual(self.register(code).status_code, 200)
        self.post(self.admin, 'admin/admissions/revoke', {'kind': 'invite', 'id': admissions.invitation_hash(code)})
        self.assertEqual(self.register(code).status_code, 403)
        code = self.code()
        with central_db() as c:
            c.execute('UPDATE midiary_invites SET expires=0 WHERE hash=?', (admissions.invitation_hash(code),))
        self.assertEqual(self.register(code).status_code, 403)

    def test_quota_inputs_and_guardian_confirmation(self):
        for count in (0, -1, True, 1.5, '2', 10001):
            self.assertEqual(self.post(self.admin, 'admin/invites', {'count': count}).status_code, 400)
        self.assertEqual(self.post(self.admin, 'admin/invites', {'minor': True}).status_code, 400)
        self.assertEqual(self.post(self.admin, 'admin/registrations/telegram', {'tg': 810001, 'minor': True}).status_code, 400)

    def test_telegram_permission_requires_verified_identity(self):
        self.assertEqual(self.post(self.admin, 'admin/registrations/telegram', {'tg': '810001'}).status_code, 200)
        self.assertEqual(self.register(telegram_id=810001).status_code, 403)
        self.assertEqual(self.register(client=self.approved_client(810002)).status_code, 403)
        client = self.approved_client(810001)
        self.assertEqual(self.register(client=client).status_code, 200)
        self.assertEqual(client.get('/api/me').get_json()['tg'], 810001)
        self.assertEqual(self.register(client=self.approved_client(810001)).status_code, 409)

    def test_grant_is_not_usable_by_max_and_can_be_revoked(self):
        admissions.allow_telegram(self.admin_owner, 810005)
        with self.assertRaises(ValueError):
            bot_registration.create_account('max', 810005, self.bot_state())
        admissions.revoke(self.admin_owner, 'telegram', 810005)
        self.assertEqual(self.register(client=self.approved_client(810005)).status_code, 403)

    def test_bot_registration_skips_code_for_allowed_id(self):
        admissions.allow_telegram(self.admin_owner, 810003, group_id='fgu:99991')
        with patch('services.telegram.tg_call', return_value={'message_id': 1}):
            bot_registration.start(810003, 'ru')
            state = bot_registration.load('telegram', 810003)
            self.assertEqual(state['step'], 'name')
            bot_registration.message(810003, 'Моё новое имя')
            nonce = state['nonce']
            for action in ('age:adult', 'terms', 'privacy', 'finish'):
                bot_registration.callback({'id': 'callback-' + action, 'from': {'id': 810003},
                    'message': {'chat': {'type': 'private', 'id': 810003}}, 'data': 'reg:' + nonce + ':' + action})
        with central_db() as c:
            member = c.execute('SELECT code,name FROM members WHERE tg=810003').fetchone()
        self.assertEqual(member['name'], 'Моё новое имя')
        self.assertEqual(owner_profile('member:' + member['code'])['group_id'], 'fgu:99991')
        self.assertIsNone(bot_registration.load('telegram', 810003))

    def test_grant_revoked_mid_registration_is_rechecked(self):
        admissions.allow_telegram(self.admin_owner, 810006)
        with patch('services.telegram.tg_call', return_value={}):
            bot_registration.start(810006, 'ru')
        admissions.revoke(self.admin_owner, 'telegram', 810006)
        with self.assertRaises(ValueError):
            bot_registration.create_account('telegram', 810006, self.bot_state())

    def test_other_group_requires_admin_and_survives_restart(self):
        self.assertEqual(self.post(self.member, 'study-group', {'faculty': 'fgu', 'group': 'fgu:99991'}).status_code, 403)
        with patch('services.timetable.start_sync'):
            result = self.post(self.admin, 'admin/members', {'member': 'existing-member', 'group_id': 'fgu:99991'})
        self.assertEqual(result.status_code, 200)
        init_db()
        self.assertEqual(self.member.get('/api/me').get_json()['group_id'], 'fgu:99991')
        self.assertEqual(self.post(self.member, 'study-group', {'faculty': 'fgu', 'group': admissions.DEFAULT_GROUP}).status_code, 403)

    def test_invitation_assigns_admin_selected_group(self):
        code = self.code(group_id='fgu:99991')
        client = self.app.test_client()
        self.assertEqual(self.register(code, client).status_code, 200)
        self.assertEqual(client.get('/api/me').get_json()['group_id'], 'fgu:99991')

    def test_fgu_catalogue_is_only_available_in_full_to_admin(self):
        rows = self.app.test_client().get('/api/groups?faculty=fgu').get_json()
        self.assertEqual([r['id'] for r in rows], ['fgu:1457'])
        self.assertEqual(self.member.get('/api/groups?faculty=fgu&admin=1').status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/groups?faculty=fgu&admin=1').status_code, 401)
        self.assertIn('fgu:99991', [r['id'] for r in self.admin.get('/api/groups?faculty=fgu&admin=1').get_json()])

    def test_member_updates_only_own_name(self):
        response = self.post(self.member, 'account/name', {'name': '  Моя   новая фамилия  ', 'member': 'someone-else'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.member.get('/api/me').get_json()['name'], 'Моя новая фамилия')
        self.assertEqual(self.member.get('/api/me').get_json()['group_id'], admissions.DEFAULT_GROUP)
        for name in ('', 'а', 'а' * 201, 123):
            self.assertEqual(self.post(self.member, 'account/name', {'name': name}).status_code, 400)

    def test_admin_endpoints_enforce_permissions_and_csrf(self):
        endpoints = {
            'admin/invites': {'count': 2}, 'admin/admissions/revoke': {'kind': 'telegram', 'id': 812},
            'admin/registrations/telegram': {'tg': 812}, 'admin/members': {'member': 'existing-member', 'group_id': 'fgu:99991'},
            'admin/support': {'enabled': False},
        }
        for path, body in endpoints.items():
            self.assertEqual(self.post(self.member, path, body).status_code, 403)
            self.assertEqual(self.admin.post('/api/' + path, json=body).status_code, 403)
        self.assertEqual(self.member.get('/api/admin/admissions').status_code, 403)
        self.assertEqual(self.member.get('/api/admin/members').status_code, 403)
        self.assertEqual(self.member.get('/api/admin/support').status_code, 403)

    def test_legacy_used_code_stays_used_after_migration(self):
        code = 'legacy-invitation'
        with central_db() as c:
            c.execute('DROP TABLE midiary_invites')
            c.execute('CREATE TABLE midiary_invites(hash TEXT PRIMARY KEY,creator TEXT,expires REAL,used_by TEXT,created REAL)')
            c.execute('INSERT INTO midiary_invites VALUES(?,?,?,?,?)', (admissions.invitation_hash(code), self.admin_owner, time.time() + 100, 'member:legacy', time.time()))
        admissions.initialize()
        admissions.initialize()
        self.assertEqual(self.register(code).status_code, 403)
        with central_db() as c:
            row = c.execute('SELECT max_uses,uses FROM midiary_invites').fetchone()
        self.assertEqual(tuple(row), (1, 1))

    def test_minors_need_special_admission_and_current_consent(self):
        normal = self.code(count=2)
        self.assertEqual(self.register(normal, age_group='minor').status_code, 403)
        minor = self.code(guardian=True, count=2)
        self.assertEqual(self.register(minor, age_group='minor').status_code, 200)
        admissions.allow_telegram(self.admin_owner, 810004, guardian=True)
        self.assertEqual(self.register(client=self.approved_client(810004), age_group='minor').status_code, 200)
        self.assertEqual(self.register(normal, privacy_accepted=False).status_code, 400)

    def test_erasing_account_does_not_reopen_shared_quota(self):
        code = self.code(count=2)
        client = self.app.test_client()
        self.assertEqual(self.register(code, client).status_code, 200)
        owner = 'member:' + client.get('/api/me').get_json()['code']
        process_one(owner, 'account')
        self.assertEqual(self.register(code).status_code, 200)
        self.assertEqual(self.register(code).status_code, 403)

    def test_guardian_code_consumption_is_idempotent_for_existing_member(self):
        code = self.code(guardian=True, count=2)
        payload = {'terms_accepted': True, 'privacy_accepted': True, 'age_group': 'minor', 'legal_version': version(), 'guardian_code': code}
        self.assertEqual(self.post(self.member, 'legal/consent', payload).status_code, 200)
        self.assertEqual(self.post(self.member, 'legal/consent', payload).status_code, 200)
        with central_db() as c:
            self.assertEqual(c.execute('SELECT uses FROM midiary_invites WHERE hash=?', (admissions.invitation_hash(code),)).fetchone()[0], 1)


class SupportDeliveryTests(AccessFixture):
    """Copies and replies use a fake Telegram transport; no live messages."""
    token = '123456789:' + 'a' * 40
    bot_id = 123456789

    def update(self, ident=1, sender=850001, message=41, **extra):
        return {'update_id': ident, 'message': {'message_id': message, 'from': {'id': sender, 'first_name': 'Пользователь', 'username': 'example_user'},
                  'chat': {'id': sender, 'type': 'private'}, 'text': 'Сообщение поддержки', **extra}}

    def transport(self, token, method, **data):
        self.calls.append((method, data))
        if method == 'getMe':
            return {'id': self.bot_id, 'is_bot': True, 'username': 'midiarybot'}
        return {'message_id': 1000 + len(self.calls)}

    def setUp(self):
        super().setUp()
        self.calls = []

    def test_support_configuration_is_encrypted_and_never_returned(self):
        with patch('services.support.call', side_effect=self.transport):
            response = self.post(self.admin, 'admin/support', {'token': self.token, 'recipient': self.admin_id, 'enabled': True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['configured'])
        with central_db() as c:
            stored = c.execute("SELECT value FROM settings WHERE key='support_token'").fetchone()[0]
        self.assertNotIn(self.token, stored)
        self.assertNotIn(self.token, response.get_data(as_text=True))
        self.assertEqual(support.configuration()[0], self.token)
        self.assertEqual(self.calls[-1], ('deleteWebhook', {'drop_pending_updates': False}))

    def test_wrong_bot_cannot_be_connected(self):
        with patch('services.support.call', return_value={'id': self.bot_id, 'is_bot': True, 'username': 'wrong_bot'}) as transport:
            response = self.post(self.admin, 'admin/support', {'token': self.token, 'recipient': self.admin_id})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(transport.call_count, 1)
        self.assertFalse(support.public_status()['configured'])

    def test_photo_and_sender_are_delivered_to_configured_admin(self):
        update = self.update(photo=[{'file_id': 'photo-reference'}])
        update['message'].pop('text')
        support.enqueue(self.bot_id, update, self.admin_id)
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, {})
        self.assertEqual([call[0] for call in self.calls], ['sendMessage', 'copyMessage', 'sendMessage'])
        self.assertEqual(self.calls[1][1]['chat_id'], self.admin_id)
        self.assertEqual(self.calls[1][1]['from_chat_id'], 850001)
        self.assertIn('850001', self.calls[0][1]['text'])
        with central_db() as c:
            self.assertEqual(c.execute('SELECT state FROM support_queue').fetchone()[0], 'delivered')

    def test_retry_resumes_after_header_without_duplicate_copy(self):
        support.enqueue(self.bot_id, self.update(), self.admin_id)
        health = {}
        def fail_copy(token, method, **data):
            if method == 'copyMessage':
                raise support.SupportAPIError(503)
            return self.transport(token, method, **data)
        with patch('services.support.call', side_effect=fail_copy):
            support.deliver_pending(self.token, self.bot_id, health)
        with central_db() as c:
            row = c.execute('SELECT state,header_id,copied_id FROM support_queue').fetchone()
            self.assertEqual(row['state'], 'pending')
            self.assertIsNotNone(row['header_id'])
            c.execute('UPDATE support_queue SET next_at=0')
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, health)
        headers = [data for method, data in self.calls if method == 'sendMessage' and data['chat_id'] == self.admin_id]
        self.assertEqual(len(headers), 1)
        self.assertEqual(len([method for method, _ in self.calls if method == 'copyMessage']), 1)

    def test_ack_retry_does_not_deliver_attachment_twice(self):
        support.enqueue(self.bot_id, self.update(), self.admin_id)
        def fail_ack(token, method, **data):
            if method == 'sendMessage' and data['chat_id'] == 850001:
                raise support.SupportAPIError(503)
            return self.transport(token, method, **data)
        with patch('services.support.call', side_effect=fail_ack):
            support.deliver_pending(self.token, self.bot_id, {})
        with central_db() as c:
            c.execute('UPDATE support_queue SET next_at=0')
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, {})
        self.assertEqual(len([method for method, _ in self.calls if method == 'copyMessage']), 1)

    def test_admin_can_reply_to_copied_message(self):
        support.enqueue(self.bot_id, self.update(), self.admin_id)
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, {})
        with central_db() as c:
            copied = c.execute('SELECT copied_id FROM support_queue').fetchone()[0]
        support.enqueue(self.bot_id, self.update(2, self.admin_id, 42, reply_to_message={'message_id': copied}), self.admin_id)
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, {})
        outgoing = [data for method, data in self.calls if method == 'copyMessage' and data['chat_id'] == 850001]
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0]['from_chat_id'], self.admin_id)
        self.assertEqual(outgoing[0]['message_id'], 42)

    def test_duplicate_updates_do_not_duplicate_delivery(self):
        update = self.update()
        support.enqueue(self.bot_id, update, self.admin_id)
        support.enqueue(self.bot_id, update, self.admin_id)
        with patch('services.support.call', side_effect=self.transport):
            support.deliver_pending(self.token, self.bot_id, {})
            support.deliver_pending(self.token, self.bot_id, {})
        self.assertEqual(len([method for method, _ in self.calls if method == 'copyMessage']), 1)

    def test_unrelated_replies_and_group_messages_are_not_relayed(self):
        self.assertFalse(support.enqueue(self.bot_id, self.update(sender=self.admin_id, reply_to_message={'message_id': 999}), self.admin_id))
        update = self.update(2)
        update['message']['chat']['type'] = 'group'
        self.assertFalse(support.enqueue(self.bot_id, update, self.admin_id))
        with central_db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM support_queue').fetchone()[0], 0)

    def test_delivery_can_be_retried_after_admin_unblocks_bot(self):
        support.enqueue(self.bot_id, self.update(), self.admin_id)
        with patch('services.support.call',side_effect=support.SupportAPIError(403)):
            support.deliver_pending(self.token,self.bot_id,{})
        with central_db() as c:
            self.assertEqual(c.execute('SELECT state FROM support_queue').fetchone()[0],'failed')
            c.execute("INSERT INTO settings VALUES('support_bot_id',?)",(str(self.bot_id),))
        self.assertEqual(self.post(self.admin,'admin/support',{'retry':True}).status_code,200)
        with patch('services.support.call',side_effect=self.transport):
            support.deliver_pending(self.token,self.bot_id,{})
        with central_db() as c:
            self.assertEqual(c.execute('SELECT state FROM support_queue').fetchone()[0],'delivered')


if __name__ == '__main__':
    unittest.main()
