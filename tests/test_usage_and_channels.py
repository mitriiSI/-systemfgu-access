"""Admin-only visit statistics and isolated Telegram/MAX publication delivery."""
import json
import time
from unittest.mock import patch

import requests

from test_admin_access import AccessFixture
from config import ADMIN_IDS
from database import central_db, central_set_setting
from services import channel_bridge as bridge, user_activity
from services.privacy import process_one


class UsageTests(AccessFixture):
    def setUp(self):
        super().setUp()
        with central_db() as c:
            c.execute('DELETE FROM account_activity')
            c.execute('DELETE FROM web_push_devices')
            c.execute('DELETE FROM privacy_deletions')
            c.execute("DELETE FROM settings WHERE key LIKE 'midiary_offsets:%:notification-channels' OR key LIKE 'privacy_broadcast_%'")

    def test_private_statistics_and_server_side_visit_tracking(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/admin/users').status_code, 401)
        self.assertEqual(self.member.get('/api/admin/users').status_code, 403)
        with central_db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM account_activity').fetchone()[0], 0)
        self.assertEqual(self.member.get('/api/me').status_code, 200)
        with central_db() as c:
            last = c.execute("SELECT last_seen FROM account_activity WHERE owner='member:existing-member'").fetchone()[0]
            self.assertAlmostEqual(last, time.time(), delta=3)
        response = self.admin.get('/api/admin/users')
        self.assertEqual(response.status_code, 200)
        value = response.get_json()
        self.assertEqual(value['counts']['total'], 1+len(ADMIN_IDS))
        self.assertEqual(value['counts']['online'], 1)
        self.assertGreater(value['tracking_since'], 0)
        self.assertNotIn('existing-member', response.get_data(as_text=True))
        self.assertNotIn(str(self.admin_id), response.get_data(as_text=True))
        self.assertTrue(value['users'][0]['active_today'])
        self.assertTrue(value['users'][0]['active_week'])

    def test_linked_channels_and_enabled_channels_are_distinct(self):
        owner = 'member:existing-member'
        with central_db() as c:
            c.execute("UPDATE members SET tg=830001 WHERE code='existing-member'")
            c.execute('INSERT INTO max_identities VALUES(?,?,?)', (830002, owner, time.time()))
            c.execute('INSERT INTO web_push_devices VALUES(?,?,?,?,?)', ('fixture-device', owner, 'secret-subscription', time.time(), time.time()))
        central_set_setting('midiary_offsets:'+owner+':notification-channels', json.dumps({'telegram': False, 'max': True, 'website': True}))
        value = self.admin.get('/api/admin/users').get_json()
        row = next(u for u in value['users'] if not u['admin'])
        self.assertTrue(row['channels']['telegram']['connected'])
        self.assertFalse(row['channels']['telegram']['available'])
        self.assertTrue(row['channels']['max']['available'])
        self.assertTrue(row['channels']['website']['available'])
        self.assertEqual(row['website_devices'], 1)
        self.assertNotIn('secret-subscription', json.dumps(value))
        central_set_setting('max_delivery_disabled:'+owner, '1')
        self.assertTrue(self.admin.get('/api/admin/users').get_json()['users'][0]['channels']['max']['blocked'])
        central_set_setting('max_delivery_disabled:'+owner, '0')

    def test_activity_is_exportable_and_erased_with_account(self):
        owner = 'member:usage-erasure-test'
        with central_db() as c:
            c.execute("INSERT INTO members(code,name) VALUES('usage-erasure-test','Удаляемый участник')")
        user_activity.touch(owner)
        value = self.client(code='usage-erasure-test').get('/api/account/export').get_json()
        self.assertIsNotNone(value['activity']['last_seen'])
        with central_db() as c:
            c.execute("INSERT INTO privacy_deletions VALUES(?,'account',?)", (owner, time.time()))
        self.assertEqual(self.admin.get('/api/admin/users').get_json()['counts']['total'], 1+len(ADMIN_IDS))
        process_one(owner, 'account')
        with central_db() as c:
            self.assertIsNone(c.execute('SELECT last_seen FROM account_activity WHERE owner=?',(owner,)).fetchone())

    def test_online_today_week_and_disabled_accounts(self):
        now = time.time()
        with central_db() as c:
            c.execute("INSERT INTO account_activity VALUES('member:existing-member',?)", (now-2*86400,))
        row = self.admin.get('/api/admin/users').get_json()['users'][0]
        self.assertFalse(row['online'])
        self.assertFalse(row['active_today'])
        self.assertTrue(row['active_week'])
        with central_db() as c:
            c.execute("UPDATE members SET active=0 WHERE code='existing-member'")
            c.execute("UPDATE account_activity SET last_seen=? WHERE owner='member:existing-member'", (now,))
        row = self.admin.get('/api/admin/users').get_json()['users'][0]
        self.assertFalse(row['active_week'])
        self.assertFalse(row['account_enabled'])


class ChannelTests(AccessFixture):
    def setUp(self):
        super().setUp()
        with central_db() as c:
            c.execute('DELETE FROM channel_deliveries')
            c.execute('DELETE FROM channel_posts')
            c.execute("DELETE FROM settings WHERE key LIKE 'channel_bridge_%'")
        support = patch('services.support.configuration', return_value=('', self.admin_id, False))
        support.start(); self.addCleanup(support.stop)
        self.config = dict(bridge.DEFAULTS, enabled=True, telegram_token='123456789:'+('A'*35),
                           telegram_channel='@test_channel', max_token='isolated-max-channel-token', max_channel='-123456')

    def configure(self, **extra):
        response = self.post(self.admin, 'admin/channel-bridge', self.config | extra)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response

    def test_default_disabled_no_external_requests_and_admin_guard(self):
        self.assertEqual(self.app.test_client().get('/api/admin/channel-bridge').status_code, 401)
        self.assertEqual(self.member.get('/api/admin/channel-bridge').status_code, 403)
        self.assertEqual(self.post(self.member, 'admin/channel-bridge', self.config).status_code, 403)
        with patch('services.channel_bridge.requests.post') as network:
            value = self.admin.get('/api/admin/channel-bridge').get_json()
            self.assertFalse(value['enabled'])
            bridge.enqueue_release(bridge.configuration())
            bridge.poll_once(bridge.configuration())
            self.assertFalse(bridge.deliver_one())
            network.assert_not_called()
        self.assertEqual(self.admin.post('/api/admin/channel-bridge', json=self.config).status_code, 403)

    def test_settings_are_encrypted_and_never_returned_to_browser(self):
        response = self.configure(enabled=False)
        value = response.get_json()
        self.assertTrue(value['telegram_configured'])
        self.assertTrue(value['max_configured'])
        self.assertNotIn(self.config['telegram_token'], response.get_data(as_text=True))
        self.assertNotIn(self.config['max_token'], response.get_data(as_text=True))
        with central_db() as c:
            raw = c.execute("SELECT value FROM settings WHERE key='channel_bridge_configuration'").fetchone()[0]
        self.assertNotIn(self.config['telegram_token'], raw)
        self.assertNotIn(self.config['max_token'], raw)
        self.assertEqual(self.post(self.admin, 'admin/channel-bridge', {'telegram_token': '', 'max_token': ''}).status_code, 200)
        self.assertEqual(bridge.configuration()['telegram_token'], self.config['telegram_token'])

    def test_invalid_credentials_targets_and_main_bot_rejected(self):
        for extra in ({'telegram_channel': 'https://evil.test'}, {'max_channel': 'https://evil.test'},
                      {'telegram_token': 'token\r\n'}, {'max_token': 'x\r\nInjected-header'},
                      {'max_channel': '0'}, {'max_channel': str(2**63)}, {'enabled': 1},
                      {'max_token': '', 'enabled': True}):
            self.assertEqual(self.post(self.admin, 'admin/channel-bridge', self.config | extra).status_code, 400, extra)
        with patch('services.channel_bridge.BOT_TOKEN', self.config['telegram_token']):
            self.assertEqual(self.post(self.admin, 'admin/channel-bridge', self.config).status_code, 400)

    def test_release_once_per_version_across_restarts(self):
        self.configure()
        bridge.enqueue_release(bridge.configuration()); bridge.enqueue_release(bridge.configuration())
        with patch('services.channel_bridge.telegram_call', return_value={'message_id': 1}) as tg, patch('services.channel_bridge.max_send', return_value={'message': {}}) as max_send:
            while bridge.deliver_one(): pass
            bridge.enqueue_release(bridge.configuration())
            self.assertFalse(bridge.deliver_one())
            self.assertEqual(tg.call_count, 1)
            self.assertEqual(max_send.call_count, 1)
        history = self.admin.get('/api/admin/channel-bridge').get_json()['history']
        self.assertEqual(len(history), 1)
        self.assertTrue(all(row['state'] == 'sent' for row in history[0]['deliveries']))

    def test_only_private_admin_text_is_forwarded_without_loops(self):
        self.configure(automatic_updates=False)
        config = bridge.configuration()
        def update(ident, sender, chat_type='private', **extra):
            return {'update_id': ident, 'message': {'from': {'id': sender}, 'chat': {'id': sender, 'type': chat_type}, 'text': 'Привет <b>MAX</b>!', **extra}}
        updates = [update(1, self.admin_id), update(2, 999999), update(3, self.admin_id, 'channel'),
                   update(4, self.admin_id, text='/help'), update(5, self.admin_id, **{'from': {'id': self.admin_id, 'is_bot': True}})]
        bridge.accept_updates(config, updates); bridge.accept_updates(config, updates)
        with patch('services.channel_bridge.telegram_call') as tg, patch('services.channel_bridge.max_send', return_value={'message': {}}) as max_send:
            self.assertTrue(bridge.deliver_one()); self.assertFalse(bridge.deliver_one())
            tg.assert_not_called()
            self.assertEqual(max_send.call_args.args[2], 'Привет <b>MAX</b>!')
        with central_db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM channel_posts').fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT value FROM settings WHERE key='channel_bridge_offset:123456789'").fetchone()[0], '6')

    def test_retry_does_not_resend_successful_channel_or_expose_errors(self):
        self.configure()
        with patch('services.channel_bridge.max_send', side_effect=requests.Timeout('token='+self.config['max_token'])):
            self.assertTrue(bridge.deliver_one())
        with patch('services.channel_bridge.telegram_call', return_value={'message_id': 1}):
            self.assertTrue(bridge.deliver_one())
        value = self.admin.get('/api/admin/channel-bridge').get_json()
        self.assertNotIn(self.config['max_token'], json.dumps(value))
        self.assertIn('uncertain', {d['state'] for d in value['history'][0]['deliveries']})
        self.assertEqual(self.post(self.admin, 'admin/channel-bridge/retry', {}).status_code, 200)
        with patch('services.channel_bridge.telegram_call') as tg, patch('services.channel_bridge.max_send', return_value={'message': {}}) as max_send:
            self.assertTrue(bridge.deliver_one()); self.assertFalse(bridge.deliver_one())
            tg.assert_not_called(); max_send.assert_called_once()

    def test_target_change_does_not_deliver_queued_message_to_new_channel(self):
        self.configure()
        self.configure(max_channel='-999999')
        with patch('services.channel_bridge.telegram_call', return_value={'message_id': 1}), patch('services.channel_bridge.max_send') as max_send:
            self.assertTrue(bridge.deliver_one()); self.assertFalse(bridge.deliver_one())
            max_send.assert_not_called()

    def test_unicode_multipart_is_ordered_and_does_not_starve_other_posts(self):
        self.configure(automatic_updates=False)
        config = bridge.configuration()
        text = '😀'*4500
        parts = bridge.chunks(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(p.encode('utf-16-le'))//2 <= 3500 for p in parts))
        with central_db() as c:
            bridge.enqueue_in(c, 'long', 'message', 'Long', text, ('max',), config)
            bridge.enqueue_in(c, 'next', 'message', 'Next', 'Следующая публикация', ('max',), config)
        with patch('services.channel_bridge.max_send', side_effect=bridge.BridgeAPIError('MAX', 403)):
            self.assertTrue(bridge.deliver_one())
        with patch('services.channel_bridge.max_send', return_value={'message': {}}) as send:
            self.assertTrue(bridge.deliver_one()); self.assertFalse(bridge.deliver_one())
            self.assertEqual(send.call_args.args[2], 'Следующая публикация')

    def test_transport_uses_fixed_urls_channel_targets_and_tls(self):
        from unittest.mock import Mock
        response = Mock(status_code=200)
        response.json.return_value = {'message': {}}
        with patch('services.channel_bridge.requests.post', return_value=response) as send:
            bridge.max_send(self.config, '-123456', 'Обычный текст <b>')
            self.assertEqual(send.call_args.args[0], 'https://platform-api2.max.ru/messages')
            self.assertEqual(send.call_args.kwargs['params']['chat_id'], -123456)
            self.assertEqual(send.call_args.kwargs['headers'], {'Authorization': self.config['max_token']})
            self.assertTrue(send.call_args.kwargs['verify'])
            self.assertFalse(send.call_args.kwargs['allow_redirects'])
            self.assertNotIn('format', send.call_args.kwargs['json'])
