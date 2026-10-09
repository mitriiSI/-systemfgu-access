"""End-to-end checks against isolated SQLite data; no bot or upstream requests."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

TEST_DATA = tempfile.TemporaryDirectory(prefix='midiary-teachers-test-')
os.environ['DATA_DIR'] = TEST_DATA.name
os.environ['SESSION_SECRET'] = 'isolated-midiary-teachers-test-secret'
os.environ['BOT_TOKEN'] = ''

from database import central_db, default_group, group_context, initialize_group, init_db, utc_now

init_db()
from app import create_app
from services.community import db


class TeacherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        sync=patch('services.timetable.start_sync',return_value=False)
        sync.start();self.addCleanup(sync.stop)
        self.code = 'teacher-test-account'
        self.owner = 'member:' + self.code
        self.client = self.app.test_client()
        with central_db() as connection:
            for table in ('content', 'schedules', 'proposals', 'revisions', 'custom_lessons', 'hidden_lessons', 'faculty_reviews'):
                connection.execute('DELETE FROM ' + table)
            connection.execute('INSERT OR REPLACE INTO members(code,name,active) VALUES(?,?,1)', (self.code, 'Тестовый участник'))
            connection.execute('INSERT OR REPLACE INTO university_profiles VALUES(?,?,?,?)', (self.owner, 'fgu', default_group(), utc_now()))
            connection.execute('DELETE FROM settings WHERE key=?', ('moderate_' + self.code,))
        self.original = {'date': '2026-10-19', 'lessons': [{'number': 2, 'periods': [{
            'disciplineFullName': 'Правоведение', 'timeStart': '11:25', 'timeEnd': '12:55',
            'teachersNameFull': 'Иванов Иван Иванович; Петров Пётр Петрович', 'classroom': '707', 'groups': '', 'typeStr': 'Семинар'
        }]}]}
        self.store_schedule(self.original)
        with self.client.session_transaction() as session:
            session['code'] = self.code
            session['csrf'] = 'test-csrf'

    def post(self, path, body):
        return self.client.post('/api/' + path, json=body, headers={'X-CSRF-Token': 'test-csrf'})

    def store_schedule(self, value):
        with db() as connection:
            connection.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)', ('1457', value['date'], json.dumps(value, ensure_ascii=False)))

    def period(self):
        return self.client.get('/api/schedule').get_json()['days'][0]['lessons'][0]['periods'][0]

    def test_existing_teacher_strings_become_individual_teachers(self):
        self.assertEqual(self.period()['teachers'], ['Иванов Иван Иванович', 'Петров Пётр Петрович'])
        ratings = self.client.get('/api/teacher-ratings').get_json()
        self.assertEqual({row['teacher'] for row in ratings}, set(self.period()['teachers']))

    def test_subject_teachers_apply_across_dates_without_changing_source(self):
        second = copy.deepcopy(self.original)
        second['date'] = '2026-10-26'
        self.store_schedule(second)
        response = self.post('schedule/teachers', {'title': '  ПРАВОВЕДЕНИЕ ', 'teachers': ['  Сидоров   Сидор Сидорович ', 'Петров Петр Петрович', 'петров пётр петрович']})
        self.assertEqual(response.get_json()['status'], 'approved')
        for day in self.client.get('/api/schedule').get_json()['days']:
            self.assertEqual(day['lessons'][0]['periods'][0]['teachers'], ['Сидоров Сидор Сидорович', 'Петров Петр Петрович'])
        with db() as connection:
            stored = json.loads(connection.execute('SELECT body FROM schedules WHERE day=?', ('2026-10-19',)).fetchone()[0])
        self.assertEqual(stored, self.original)

    def test_teacher_override_survives_upstream_refresh(self):
        self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': ['Новый преподаватель', 'Другой преподаватель']})
        refreshed = copy.deepcopy(self.original)
        refreshed['lessons'][0]['periods'][0]['teachersNameFull'] = 'Преподаватель из обновления'
        self.store_schedule(refreshed)
        self.assertEqual(self.period()['teachers'], ['Новый преподаватель', 'Другой преподаватель'])

    def test_restore_uses_upstream_teachers(self):
        self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': ['Новый преподаватель']})
        response = self.post('schedule/teachers', {'title': 'Правоведение', 'restore': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.period()['teachers'], ['Иванов Иван Иванович', 'Петров Пётр Петрович'])

    def test_hidden_lesson_stays_hidden_after_teacher_change(self):
        ident = self.period()['_diary_id']
        self.assertEqual(self.post('schedule/hide', {'id': ident, 'date': '2026-10-19'}).status_code, 200)
        self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': ['Новый преподаватель']})
        self.assertEqual(self.client.get('/api/schedule').get_json()['days'][0]['lessons'], [])

    def test_subject_override_is_isolated_from_other_groups(self):
        self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': ['Только для ФГУ']})
        key = 'geo:teacher-isolation'
        with central_db() as connection:
            connection.execute('INSERT OR REPLACE INTO university_groups VALUES(?,?,?,?,?,?,?,NULL)', (key, 'geo', 'isolated-geo', 'Тестовая группа', 'Бакалавриат', 1, 'geo'))
        initialize_group(key)
        with group_context(key), db() as connection:
            connection.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)', ('isolated-geo', self.original['date'], json.dumps(self.original)))
        with central_db() as connection:
            connection.execute('UPDATE university_profiles SET faculty=?,group_id=? WHERE owner=?', ('geo', key, self.owner))
        self.assertEqual(self.period()['teachers'], ['Иванов Иван Иванович', 'Петров Пётр Петрович'])

    def test_moderated_changes_wait_for_approval(self):
        with central_db() as connection:
            connection.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('moderate_' + self.code, '1'))
        response = self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': ['На подтверждении']})
        self.assertEqual(response.get_json()['status'], 'pending')
        self.assertNotIn('На подтверждении', self.period()['teachers'])
        with db() as connection:
            proposal = connection.execute('SELECT * FROM proposals').fetchone()
        self.assertEqual(proposal['kind'], 'subject_teachers')
        self.assertEqual(json.loads(proposal['body']), ['На подтверждении'])

    def test_invalid_lists_and_unknown_subjects_are_rejected(self):
        for value in ('Иванов', [123], ['а' * 201], ['Имя'] * 11, None):
            with self.subTest(value=value):
                self.assertEqual(self.post('schedule/teachers', {'title': 'Правоведение', 'teachers': value}).status_code, 400)
        self.assertEqual(self.post('schedule/teachers', {'title': 'Неизвестный предмет', 'teachers': ['Иванов']}).status_code, 404)

    def custom_body(self):
        return {'title': 'Новый предмет', 'date': '2026-10-19', 'start': '15:00', 'end': '16:00', 'type': 'lesson',
                'recurrence': 'weekly', 'visibility': 'personal', 'teachers': ['Новый первый преподаватель', 'Новый второй преподаватель']}

    def test_custom_lesson_keeps_all_teachers_and_exposes_individual_reviews(self):
        response = self.post('schedule/custom', self.custom_body())
        self.assertEqual(response.status_code, 200)
        events = self.client.get('/api/schedule/events?start=2026-10-19&end=2026-10-26').get_json()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['teachers'], self.custom_body()['teachers'])
        ratings = self.client.get('/api/teacher-ratings').get_json()
        self.assertTrue(set(self.custom_body()['teachers']).issubset({row['teacher'] for row in ratings}))
        for name in self.custom_body()['teachers']:
            response = self.post('teacher-reviews', {'teacher': name, 'clarity': 4, 'knowledge': 5, 'communication': 3,
                                                     'recommend': True, 'public_author': False, 'comment': 'Отдельный отзыв'})
            self.assertEqual(response.status_code, 200)

    def test_shared_events_accept_multiple_teachers(self):
        response = self.post('schedule/events', self.custom_body())
        self.assertEqual(response.status_code, 200)
        events = self.client.get('/api/schedule/events?start=2026-10-19&end=2026-10-19').get_json()
        self.assertEqual(events[0]['teachers'], self.custom_body()['teachers'])

    def test_legacy_single_teacher_payload_remains_supported(self):
        body = self.custom_body()
        del body['teachers']
        body['teacher'] = 'Один преподаватель'
        self.assertEqual(self.post('schedule/custom', body).status_code, 200)
        events = self.client.get('/api/schedule/events?start=2026-10-19&end=2026-10-19').get_json()
        self.assertEqual(events[0]['teachers'], ['Один преподаватель'])

    def test_teacher_changes_require_csrf(self):
        response = self.client.post('/api/schedule/teachers', json={'title': 'Правоведение', 'teachers': ['Иванов']})
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
