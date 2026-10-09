"""Browser links, real bot command handlers and signed mini-app identities."""
import hashlib
import hmac
import json
import os
import ssl
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlencode
from unittest.mock import patch

from test_admin_access import AccessFixture
from database import central_db, central_set_setting
from bot.handlers import handle_command, handle_callback
from bot import max_worker
from services import max_platform
from services.network_trust import certificate_bundle

MAX_CREDENTIALS = {'token':'isolated-max-token','secret':'isolated-max-secret',
                   'ca_bundle':str(Path(max_platform.__file__).with_name('max_root_ca.pem'))}


def token_from(response):
    query=parse_qs(urlsplit(response.get_json()['url']).query)
    return (query.get('start') or query['startapp'])[0][6:]


def signed(user_id, token, stamp=None, **extra):
    fields = {'auth_date':str(int(time.time()) if stamp is None else stamp),'user':json.dumps({'id':user_id}),**extra}
    key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(k+'='+v for k,v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class MessengerFixture(AccessFixture):
    def setUp(self):
        super().setUp()
        central_set_setting('bot_username','isolated_test_bot')
        self.browser=self.app.test_client();self.user=81234567
        with central_db() as c:
            c.execute('DELETE FROM max_logins')
            c.execute('UPDATE members SET tg=? WHERE code=?',(self.user,'existing-member'))
            max_platform.bind(c,self.user,'member:existing-member')
        credentials=patch('services.max_platform.credentials',return_value=MAX_CREDENTIALS)
        credentials.start();self.addCleanup(credentials.stop)

    def approve_telegram(self,token):
        message={'from':{'id':self.user},'chat':{'type':'private','id':self.user},'message_id':1,'text':'/start login_'+token}
        with patch('bot.handlers.tg_call') as send:
            handle_command(message)
            prompt=send.call_args.kwargs
            self.assertIn('Подтвердить вход',prompt['text'])
            callback=prompt['reply_markup']['inline_keyboard'][0][0]['callback_data']
            self.assertLessEqual(len(callback.encode()),64)
            handle_callback({'id':'callback','from':{'id':self.user},'data':callback,'message':message})

    def approve_max(self,token):
        event=max_worker.normalize({'update_type':'bot_started','user':{'user_id':self.user},'timestamp':int(time.time()*1000),'payload':'login_'+token})
        with patch('services.max_platform.send_telegram') as send:
            max_worker.process(event)
            prompt=send.call_args.args[1]
            self.assertIn('Подтвердить вход',prompt['text'])
            callback=prompt['reply_markup']['inline_keyboard'][0][0]['callback_data']
            max_worker.confirm_login({'user':self.user,'payload':callback,'callback':'callback','mid':'message'})

class MessengerLoginTests(MessengerFixture):
    def test_max_mini_app_approves_the_original_browser_with_signed_start_parameter(self):
        started=self.browser.post('/api/max/browser/start',json={});token=token_from(started)
        self.assertIn('?startapp=login_',started.get_json()['url'])
        native=self.app.test_client()
        raw=signed(self.user,MAX_CREDENTIALS['token'],start_param='login_'+token)
        response=native.post('/api/max/auth',json={'initData':raw}).get_json()
        self.assertTrue(response['ok'])
        self.assertEqual(self.browser.post('/api/max/browser/poll',json={}).get_json()['status'],'pending')
        self.assertEqual(native.post('/api/max/browser/confirm',json={'token':response['browser_confirmation']['token'],'approve':True},headers={'X-CSRF-Token':response['csrf']}).status_code,200)
        foreign=self.app.test_client()
        self.assertEqual(foreign.post('/api/max/browser/poll',json={}).get_json()['status'],'expired')
        self.assertTrue(self.browser.post('/api/max/browser/poll',json={}).get_json()['ok'])

    def test_forged_max_start_parameter_cannot_approve_a_browser(self):
        started=self.browser.post('/api/max/browser/start',json={});token=token_from(started)
        raw=signed(self.user,MAX_CREDENTIALS['token']).replace('user=', 'start_param=login_'+token+'&user=')
        self.assertEqual(self.app.test_client().post('/api/max/auth',json={'initData':raw}).status_code,401)
        self.assertEqual(self.browser.post('/api/max/browser/poll',json={}).get_json()['status'],'pending')

    def test_telegram_first_link_remains_valid_after_repeated_tap(self):
        first=self.browser.post('/api/browser/start',json={})
        second=self.browser.post('/api/browser/start',json={})
        self.assertEqual(first.get_json()['url'],second.get_json()['url'])
        self.assertEqual(self.browser.post('/api/browser/poll',json={}).get_json()['status'],'pending')
        self.approve_telegram(token_from(first))
        self.assertTrue(self.browser.post('/api/browser/poll',json={}).get_json()['ok'])
        self.assertEqual(self.browser.get('/api/me').get_json()['name'],'Старое имя')

    def test_max_first_link_remains_valid_after_repeated_tap(self):
        first=self.browser.post('/api/max/browser/start',json={})
        second=self.browser.post('/api/max/browser/start',json={})
        self.assertEqual(first.get_json()['url'],second.get_json()['url'])
        self.approve_max(token_from(first))
        self.assertTrue(self.browser.post('/api/max/browser/poll',json={}).get_json()['ok'])
        self.assertEqual(self.browser.get('/api/me').get_json()['name'],'Старое имя')

    def test_approval_cannot_sign_in_a_different_browser(self):
        for platform,prefix,approve in (('telegram','',self.approve_telegram),('max','max/',self.approve_max)):
            with self.subTest(platform=platform):
                client=self.app.test_client();response=client.post('/api/'+prefix+'browser/start',json={})
                approve(token_from(response))
                other=self.app.test_client()
                self.assertEqual(other.post('/api/'+prefix+'browser/poll',json={}).get_json()['status'],'expired')
                self.assertTrue(client.post('/api/'+prefix+'browser/poll',json={}).get_json()['ok'])

    def test_expired_requests_are_replaced_and_cannot_be_approved(self):
        for prefix,table in (('','browser_logins'),('max/','max_logins')):
            client=self.app.test_client();first=client.post('/api/'+prefix+'browser/start',json={})
            token=token_from(first)
            with central_db() as c:c.execute('UPDATE '+table+' SET expires=0 WHERE token=?',(token,))
            self.assertEqual(client.post('/api/'+prefix+'browser/poll',json={}).get_json()['status'],'expired')
            second=client.post('/api/'+prefix+'browser/start',json={})
            self.assertNotEqual(token,token_from(second))

    def test_revoked_account_cannot_confirm_a_browser_login(self):
        response=self.browser.post('/api/browser/start',json={});token=token_from(response)
        with central_db() as c:c.execute('UPDATE members SET active=0 WHERE code=?',('existing-member',))
        with patch('bot.handlers.tg_call'):
            handle_callback({'id':'callback','from':{'id':self.user},'data':'login:'+token,'message':{'chat':{'type':'private','id':self.user},'message_id':1}})
        self.assertEqual(self.browser.post('/api/browser/poll',json={}).get_json()['status'],'pending')

    def test_signed_telegram_and_max_mini_apps_sign_in_existing_owner(self):
        with patch('routes.auth.TOKEN','isolated-telegram-token'):
            response=self.browser.post('/api/auth',json={'initData':signed(self.user,'isolated-telegram-token')})
        self.assertTrue(response.get_json()['ok'])
        client=self.app.test_client()
        response=client.post('/api/max/auth',json={'initData':signed(self.user,MAX_CREDENTIALS['token'])})
        self.assertTrue(response.get_json()['ok'])
        self.assertEqual(client.get('/api/me').get_json()['name'],'Старое имя')

    def test_expired_or_forged_mini_app_data_is_rejected(self):
        for prefix,token in (('','isolated-telegram-token'),('max/',MAX_CREDENTIALS['token'])):
            with patch('routes.auth.TOKEN','isolated-telegram-token'):
                for raw in (signed(self.user,token,int(time.time())-4000),signed(self.user,'forged-token')):
                    self.assertEqual(self.app.test_client().post('/api/'+prefix+'auth',json={'initData':raw}).status_code,401)

    def test_max_trust_accepts_runtime_and_russian_roots(self):
        import requests
        base=requests.certs.where()
        with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':base}):
            merged=certificate_bundle(MAX_CREDENTIALS['ca_bundle'])
        context=ssl.create_default_context(cafile=merged)
        names={value for certificate in context.get_ca_certs() for group in certificate['subject'] for key,value in group if key=='commonName'}
        self.assertIn('Russian Trusted Root CA',names)
        self.assertGreater(len(context.get_ca_certs()),1)
