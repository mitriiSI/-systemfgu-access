"""Adversarial requests against disposable accounts and databases only."""
import io
import json
import time
from pathlib import Path
from unittest.mock import patch

from test_admin_access import AccessFixture
from config import DATA_DIR
from database import central_db, group_context, initialize_group, get_setting, utc_now
from services.admissions import set_profile
from services import community


class SecurityTests(AccessFixture):
    def setUp(self):
        super().setUp()
        initialize_group('fgp:101')
        initialize_group('fgu:99991')
        with central_db() as c:
            c.execute("DELETE FROM subscription_overrides WHERE owner IN ('member:existing-member','member:security-other')")
            for owner in ('member:existing-member', self.admin_owner):
                set_profile(c, owner, 'fgp:101')
            c.execute("INSERT INTO members(code,name) VALUES('security-other','Другой участник')")
            set_profile(c, 'member:security-other', 'fgp:101')
            c.execute("INSERT INTO members(code,name) VALUES('security-foreign','Чужая группа')")
            set_profile(c, 'member:security-foreign', 'fgu:99991')
        self.other = self.client(code='security-other')
        self.foreign = self.client(code='security-foreign')
        self.anonymous = self.app.test_client()
        self.private_id = 'a' * 32
        self.private_file = 'b' * 48
        self.shared_file = 'c' * 48
        self.item = '101|2026-10-07|extra|' + self.private_id
        with group_context('fgp:101'), community.db() as c:
            for table in ('custom_lessons', 'files', 'content', 'personal', 'deadlines', 'schedule_imports', 'schedules'):
                c.execute('DELETE FROM ' + table)
            event = {'title': 'Личная пара', 'date': '2026-10-07', 'start': '09:00', 'end': '10:30', 'type': 'lesson', 'recurrence': 'once', 'visibility': 'personal'}
            c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)', (self.private_id, 'member:existing-member', get_setting('group_id'), json.dumps(event)))
            for ident, item in ((self.private_file, self.item), (self.shared_file, '101|2026-10-07|1|Общая пара|')):
                c.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', (ident, 'lesson', item, 'Документ', 'note.txt', 'Участник', utc_now(), 12))
                (DATA_DIR / 'files' / ident).write_bytes(b'private data')
            c.execute('INSERT INTO content VALUES(?,?,?,?,?)', ('homework', self.item, 'Личное задание', 'Участник', utc_now()))
            c.execute('INSERT INTO deadlines VALUES(?,?,?,?,?)', (self.item, '101', 'Личный срок', '2026-10-08T09:00:00+03:00', utc_now()))
            c.execute('INSERT INTO personal VALUES(?,?,?,?,?)', ('member:existing-member', 'note', 'private-note', 'Личная заметка', utc_now()))

    def test_anonymous_cannot_read_private_data_or_admin_settings(self):
        for path in ('me', 'personal', 'account/export', 'study-materials', 'admin/members', 'admin/subscriptions', 'files/' + self.private_file):
            with self.subTest(path=path):
                self.assertEqual(self.anonymous.get('/api/' + path).status_code, 401)

    def test_forged_session_cookie_cannot_authenticate(self):
        self.anonymous.set_cookie('session', 'eyJ0ZyI6MjAxMTUyODU0OCwiY3NyZiI6ImV2aWwifQ.invalid.invalid')
        self.assertEqual(self.anonymous.get('/api/account/export').status_code, 401)

    def test_personal_lesson_files_are_not_listed_to_other_users(self):
        for path in ('files?scope=lesson&item=' + self.item, 'study-materials', 'lesson-detail?item=' + self.item):
            with self.subTest(path=path):
                response = self.other.get('/api/' + path)
                self.assertNotIn(self.private_file, response.get_data(as_text=True))
        self.assertIn(self.private_file, self.member.get('/api/study-materials').get_data(as_text=True))
        self.assertIn(self.shared_file, self.other.get('/api/study-materials').get_data(as_text=True))

    def test_schedule_attachment_index_enforces_owner_and_group(self):
        literature_id = 'd' * 48
        with group_context('fgp:101'), community.db() as c:
            c.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', (literature_id, 'literature', '1', 'Книга', 'book.txt', 'Участник', utc_now(), 12))
        self.assertEqual(self.anonymous.get('/api/schedule').status_code, 401)
        own = self.member.get('/api/schedule').get_json()['files']
        shared = self.other.get('/api/schedule').get_json()['files']
        self.assertEqual({row['id'] for row in own}, {self.private_file, self.shared_file})
        self.assertEqual({row['id'] for row in shared}, {self.shared_file})
        self.assertEqual(self.foreign.get('/api/schedule').get_json()['files'], [])
        for row in own:
            self.assertEqual(set(row), {'id', 'scope', 'item', 'title', 'filename', 'size'})

    def test_personal_lesson_download_and_max_ticket_enforce_owner(self):
        with self.member.get('/api/files/' + self.private_file) as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.other.get('/api/files/' + self.private_file).status_code, 404)
        self.assertEqual(self.foreign.get('/api/files/' + self.private_file).status_code, 404)
        self.assertEqual(self.post(self.other, 'max/files/' + self.private_file + '/ticket', {}).status_code, 404)
        with self.other.get('/api/files/' + self.shared_file) as response:
            self.assertEqual(response.status_code, 200)

    def test_cannot_upload_to_someone_elses_private_lesson(self):
        response = self.other.post('/api/files', data={'scope': 'lesson', 'item': self.item, 'file': (io.BytesIO(b'test'), 'test.txt')}, headers={'X-CSRF-Token': 'test-csrf'})
        self.assertEqual(response.status_code, 404)

    def test_private_homework_and_deadlines_are_not_shared(self):
        self.assertNotIn('Личное задание', json.dumps(self.other.get('/api/content').get_json(),ensure_ascii=False))
        self.assertNotIn('Личный срок', json.dumps(self.other.get('/api/deadlines').get_json(),ensure_ascii=False))
        self.assertIn('Личное задание', json.dumps(self.member.get('/api/content').get_json(),ensure_ascii=False))
        self.assertEqual(self.post(self.other, 'content', {'kind': 'homework', 'item': self.item, 'body': 'Подмена'}).status_code, 404)
        self.assertEqual(self.post(self.other, 'deadlines', {'item': self.item, 'title': 'Подмена', 'due': '2026-10-08T09:00:00+03:00'}).status_code, 404)

    def test_export_and_personal_notes_ignore_forged_owner(self):
        response = self.other.get('/api/account/export?owner=member:existing-member')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Личная заметка', response.get_data(as_text=True))
        self.assertEqual(self.post(self.other, 'personal', {'owner': 'member:existing-member', 'kind': 'note', 'item': 'private-note', 'body': 'Подмена'}).status_code, 200)
        self.assertIn('Личная заметка', json.dumps(self.member.get('/api/personal').get_json(),ensure_ascii=False))

    def test_members_cannot_change_prices_or_grant_free_access(self):
        for body in ({'base_price': 0}, {'member': 'existing-member', 'free': True}, {'member': 'security-other', 'price': 0}):
            self.assertEqual(self.post(self.member, 'admin/subscriptions', body).status_code, 403)
        self.assertEqual(self.member.get('/api/admin/subscriptions').status_code, 403)
        with central_db() as c:
            self.assertFalse(c.execute("SELECT 1 FROM subscription_overrides WHERE owner='member:existing-member'").fetchone())

    def test_shared_import_requires_administrator_and_is_atomic(self):
        entry = {'date': '2026-10-07', 'number': 1, 'title': 'Подмена', 'start': '09:00', 'end': '10:30', 'teacher': '', 'room': '', 'type': 'Пара'}
        with group_context('fgp:101'), community.db() as c:
            c.execute('INSERT INTO schedule_imports VALUES(?,?,?,?,?,?,0,0)', ('security-preview', 'member:existing-member', time.time(), time.time()+300, json.dumps([entry]), 'test.xlsx'))
        response = self.post(self.member, 'schedule/import/commit', {'token': 'security-preview', 'visibility': 'group', 'replace': True})
        self.assertEqual(response.status_code, 403)
        with group_context('fgp:101'), community.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM schedules').fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT committed FROM schedule_imports WHERE id='security-preview'").fetchone()[0], 0)

    def test_missing_csrf_and_cross_site_login_are_rejected(self):
        self.assertEqual(self.member.post('/api/personal', json={'kind': 'note', 'item': 'test', 'body': 'csrf'}).status_code, 403)
        self.assertEqual(self.anonymous.post('/api/browser/id', json={'code': 'existing-member'}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.anonymous.post('/api/browser/id', json={'code': 'existing-member'}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_non_ascii_csrf_and_webhook_headers_are_rejected_without_crash(self):
        self.assertEqual(self.member.post('/api/personal',json={'kind':'note','item':'test','body':'test'},headers={'X-CSRF-Token':'\u00ff'}).status_code,403)
        with patch('services.max_platform.credentials',return_value={'token':'test-token','secret':'test-secret'}):
            self.assertEqual(self.anonymous.post('/api/max/webhook',json={},headers={'X-Max-Bot-Api-Secret':'\u00ff'}).status_code,403)

    def test_forged_forwarding_headers_cannot_bypass_login_limit(self):
        statuses = [self.anonymous.post('/api/browser/id', json={'code': 'wrong-code'}, headers={'X-Forwarded-For': '198.51.100.'+str(n), 'CF-Connecting-IP': '203.0.113.'+str(n)}).status_code for n in range(12)]
        self.assertEqual(statuses[-1], 429)

    def test_empty_login_poll_is_rate_limited(self):
        statuses=[self.anonymous.post('/api/browser/poll',json={}).status_code for _ in range(122)]
        self.assertEqual(statuses[0],200)
        self.assertEqual(statuses[-1],429)

    def test_public_catalogue_reads_cache_without_external_requests(self):
        with central_db() as c:
            c.execute("INSERT OR REPLACE INTO university_groups VALUES('geo:security-cache','geo','security-cache','Тестовая группа','Бакалавриат',1,'geo',NULL)")
        with patch('services.external_schedules.geo_data',side_effect=AssertionError('Unexpected network')):
            response=self.anonymous.get('/api/groups?faculty=geo')
        self.assertEqual(response.status_code,200)
        self.assertIn('geo:security-cache',{row['id'] for row in response.get_json()})

    def test_non_object_json_is_rejected_without_server_error(self):
        self.assertEqual(self.anonymous.post('/api/browser/id', json=['not an object']).status_code, 400)

    def test_oversized_login_request_is_rejected(self):
        self.assertEqual(self.anonymous.post('/api/browser/id', json={'code': 'x'*100000}).status_code, 413)

    def test_traversal_and_sql_injection_do_not_expose_files(self):
        for path in ('/api/files/..%2f..%2f.env', '/static/..%2f.env', '/api/files/%27%20OR%201%3D1--'):
            self.assertIn(self.member.get(path).status_code, (400, 404))
        self.assertEqual(self.anonymous.post('/api/browser/id', json={'code': "' OR 1=1--"}).status_code, 403)

    def test_api_does_not_return_member_access_secrets_to_other_users(self):
        for path in ('content', 'schedule/events?start=2026-10-01&end=2026-10-31', 'study-materials', 'teacher-ratings'):
            response = self.other.get('/api/' + path)
            self.assertNotIn('existing-member', response.get_data(as_text=True))

    def test_trusted_proxy_uses_only_the_last_forwarded_address(self):
        with patch.dict(self.app.config, {'TRUSTED_PROXY_IPS': {'192.0.2.10'}}):
            statuses = [self.anonymous.post('/api/browser/id', json={'code': 'wrong'}, headers={'X-Forwarded-For': '198.51.100.'+str(n)+', 203.0.113.20'}, environ_base={'REMOTE_ADDR': '192.0.2.10'}).status_code for n in range(12)]
        self.assertEqual(statuses[-1], 429)

    def test_security_headers_allow_messenger_frames_and_block_inline_attacks(self):
        response=self.anonymous.get('/')
        policy=response.headers['Content-Security-Policy']
        self.assertIn("object-src 'none'",policy)
        self.assertIn('https://web.telegram.org',policy)
        self.assertIn('https://*.max.ru',policy)
        self.assertNotIn("script-src 'self' 'unsafe-inline'",policy)
        self.assertIn('max-age=',response.headers['Strict-Transport-Security'])
        response.close()

    def test_uploads_stop_before_exhausting_disk_space_or_owner_quota(self):
        data=lambda:{'scope':'lesson','item':'101|2026-10-07|1|Общая пара|','file':(io.BytesIO(b'test'),'test.txt')}
        from collections import namedtuple
        usage=namedtuple('Usage','total used free')
        with patch('services.upload_limits.shutil.disk_usage',return_value=usage(1,1,0)):
            response=self.member.post('/api/files',data=data(),headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,503)
        with patch('services.upload_limits.MAX_FILES',0):
            response=self.member.post('/api/files',data=data(),headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,400)
