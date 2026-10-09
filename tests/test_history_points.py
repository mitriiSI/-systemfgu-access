"""Private grade records, exact totals, semester boundaries and data erasure."""
import test_subgroups as fixtures
from database import central_db
from services.admissions import set_profile
from services.history_points import semester
from services.privacy import process_one
from datetime import date


class HistoryPointsTests(fixtures.GroupFixture):
    def setUp(self):
        super().setUp()
        with central_db() as c:
            c.execute('DELETE FROM history_points')
            set_profile(c, self.admin_owner, fixtures.GROUP)

    def entry(self, client=None, **changes):
        body = dict(date='2026-10-09', title='Ответ на семинаре', points=3.5, category='seminar')
        body.update(changes)
        return self.post(client or self.member, 'history-points', body)

    def ledger(self, client=None, term='2026-2'):
        return (client or self.member).get('/api/history-points?term=' + term).get_json()

    def simple_ledger(self, client=None):
        return (client or self.member).get('/api/history-points?simple=1').get_json()

    def test_single_number_adds_exact_total_without_metadata(self):
        for points in (0.1, 0.2, 3):
            self.assertEqual(self.post(self.member, 'history-points', {'points': points}).status_code, 201)
        result = self.simple_ledger()
        self.assertEqual(result['total'], 3.3)
        self.assertEqual(len(result['entries']), 3)
        self.assertEqual(set(result), {'total', 'entries'})
        self.assertTrue(all(set(row) == {'id', 'points'} for row in result['entries']))
        summary = self.member.get('/api/history-points/summary').get_json()
        self.assertEqual((summary['total'], summary['count']), (3.3, 3))

    def test_simple_total_keeps_old_records_and_ignores_dates(self):
        for value, points in [('2025-01-15', 0.1), ('2026-08-31', 0.2), ('2027-09-01', 2.5)]:
            self.assertEqual(self.entry(date=value, points=points).status_code, 201)
        self.assertEqual(self.simple_ledger()['total'], 2.8)
        self.assertEqual(self.member.get('/api/history-points/summary').get_json()['total'], 2.8)
        self.assertEqual(self.ledger(term='2026-1')['total'], 0.2)

    def test_simple_edit_preserves_old_metadata_and_created(self):
        original = self.entry(date='2025-08-05', title='Старая запись', category='test').get_json()['entry']
        response = self.post(self.member, 'history-points', {'id': original['id'], 'points': 4.75})
        self.assertEqual(response.status_code, 200)
        edited = response.get_json()['entry']
        for key in ('id', 'date', 'category', 'title', 'created'):
            self.assertEqual(edited[key], original[key])
        self.assertEqual(self.simple_ledger()['total'], 4.75)

    def test_simple_scores_remain_private_and_group_scoped(self):
        ident = self.post(self.member, 'history-points', {'points': 5}).get_json()['entry']['id']
        for client in (self.other, self.admin):
            self.assertEqual(self.simple_ledger(client), {'total': 0, 'entries': []})
            self.assertEqual(client.get('/api/history-points/summary').get_json()['total'], 0)
            self.assertEqual(self.post(client, 'history-points', {'id': ident, 'points': 9}).status_code, 404)
        with central_db() as c:
            set_profile(c, fixtures.OWNER, 'fgu:99991')
        self.assertEqual(self.simple_ledger()['total'], 0)
        with central_db() as c:
            set_profile(c, fixtures.OWNER, fixtures.GROUP)
        self.assertEqual(self.simple_ledger()['total'], 5)

    def test_simple_invalid_numbers_and_identity_injection_are_rejected(self):
        for body in ({}, {'points': True}, {'points': None}, {'points': '2'}, {'points': -1},
                     {'points': 0.001}, {'points': 1000.01}, {'points': 1, 'owner': 'other'},
                     {'points': 1, 'group_id': 'fgu:99991'}, {'points': 1, 'id': 'short'},
                     [1], [dict(points=1)]):
            with self.subTest(body=body):
                self.assertEqual(self.post(self.member, 'history-points', body).status_code, 400)
        self.assertEqual(self.simple_ledger()['entries'], [])

    def test_create_edit_delete_recomputes_exact_total_and_preserves_created(self):
        first = self.entry(points=0.1)
        self.assertEqual(first.status_code, 201)
        ident = first.get_json()['entry']['id']
        self.assertEqual(self.entry(points=0.2).status_code, 201)
        self.assertEqual(self.ledger()['total'], 0.3)
        edited = self.entry(id=ident, points=2.01, title='Исправленный ответ')
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()['entry']['created'], first.get_json()['entry']['created'])
        self.assertEqual(self.ledger()['total'], 2.21)
        summaries = self.member.get('/api/history-points/summary').get_json()['totals']
        self.assertEqual(summaries, [{'term': '2026-2', 'total': 2.21, 'count': 2}])
        response = self.member.delete('/api/history-points/' + ident, headers={'X-CSRF-Token': 'test-csrf'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ledger()['total'], 0.2)
        self.assertEqual(len(self.ledger()['entries']), 1)

    def test_other_members_and_admin_cannot_read_change_or_delete_own_records(self):
        record = self.entry(title='Моя закрытая запись').get_json()['entry']
        for client in (self.other, self.admin):
            self.assertEqual(self.ledger(client)['entries'], [])
            self.assertEqual(client.get('/api/history-points/summary').get_json()['totals'], [])
            self.assertEqual(self.entry(client, id=record['id']).status_code, 404)
            self.assertEqual(client.delete('/api/history-points/' + record['id'], headers={'X-CSRF-Token': 'test-csrf'}).status_code, 404)
        payload = self.ledger()
        self.assertNotIn('owner', str(payload))
        self.assertNotIn('group_id', str(payload))
        self.assertEqual(payload['total'], 3.5)

    def test_school_group_switch_does_not_mix_course_totals(self):
        self.entry()
        with central_db() as c:
            set_profile(c, fixtures.OWNER, 'fgu:99991')
        self.assertEqual(self.ledger()['total'], 0)
        self.assertEqual(self.entry(points=8).status_code, 201)
        self.assertEqual(self.ledger()['total'], 8)
        with central_db() as c:
            set_profile(c, fixtures.OWNER, fixtures.GROUP)
        self.assertEqual(self.ledger()['total'], 3.5)

    def test_semesters_include_january_and_separate_spring_and_next_autumn(self):
        for value, points in [('2026-08-31', 1), ('2026-09-01', 2), ('2027-01-31', 3),
                              ('2027-02-01', 4), ('2027-09-01', 5)]:
            self.assertEqual(self.entry(date=value, points=points).status_code, 201)
        for term, total in [('2026-1', 1), ('2026-2', 5), ('2027-1', 4), ('2027-2', 5)]:
            self.assertEqual(self.ledger(term=term)['total'], total)
        self.assertEqual(semester(date(2027, 1, 5)), '2026-2')

    def test_edit_date_moves_record_to_new_semester(self):
        ident = self.entry().get_json()['entry']['id']
        self.assertEqual(self.entry(id=ident, date='2027-02-02', points=2.75).status_code, 200)
        self.assertEqual(self.ledger()['entries'], [])
        self.assertEqual(self.ledger(term='2027-1')['total'], 2.75)

    def test_invalid_values_and_identity_injection_are_rejected_without_saving(self):
        for changes in ({'points': True}, {'points': None}, {'points': '3.5'}, {'points': -1},
                        {'points': 1000.01}, {'points': 0.001}, {'date': '2026-02-30'},
                        {'date': '20261009'}, {'date': '1999-12-31'}, {'title': ''},
                        {'title': 'x' * 161}, {'title': 'two\nlines'}, {'category': []},
                        {'category': 'invalid'}, {'owner': 'member:second-member'},
                        {'group_id': 'fgu:99991'}, {'id': 10}, {'id': 'short'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.entry(**changes).status_code, 400)
        self.assertEqual(self.ledger()['entries'], [])
        for term in ('2026', '../../data', '2026-3', '1998-2'):
            self.assertEqual(self.member.get('/api/history-points?term=' + term).status_code, 400)

    def test_plain_text_titles_and_all_assignment_types(self):
        title = '<img src=x onerror=alert(1)>'
        for kind in ('seminar', 'homework', 'test', 'exam', 'other'):
            self.assertEqual(self.entry(title=title, category=kind, points=0).status_code, 201)
        self.assertEqual([row['title'] for row in self.ledger()['entries']], [title] * 5)

    def test_authentication_and_csrf_are_required(self):
        anon = self.app.test_client()
        for path in ('/api/history-points', '/api/history-points/summary'):
            self.assertEqual(anon.get(path).status_code, 401)
        self.assertEqual(self.member.post('/api/history-points', json={}).status_code, 403)
        ident = self.entry().get_json()['entry']['id']
        self.assertEqual(self.member.delete('/api/history-points/' + ident).status_code, 403)
        self.assertEqual(self.ledger()['total'], 3.5)

    def test_semester_entry_limit_allows_edits_and_is_private(self):
        from unittest.mock import patch
        with patch('services.history_points.MAX_ENTRIES', 2):
            ident = self.entry().get_json()['entry']['id']
            self.assertEqual(self.entry().status_code, 201)
            self.assertEqual(self.entry().status_code, 400)
            self.assertEqual(self.entry(id=ident, points=8).status_code, 200)
            self.assertEqual(self.entry(self.other).status_code, 201)
            self.assertEqual(self.entry(date='2027-02-02').status_code, 201)
        self.assertEqual(self.ledger()['total'], 11.5)

    def test_export_and_personal_erasure_include_only_the_owner_points(self):
        self.entry(title='Свои баллы')
        self.entry(self.other, title='Чужие баллы', points=9)
        result = self.member.get('/api/account/export').get_json()['history_points']
        self.assertEqual([row['title'] for row in result], ['Свои баллы'])
        self.assertEqual(result[0]['points'], 3.5)
        self.assertNotIn('owner', str(result))
        process_one(fixtures.OWNER, 'personal')
        self.assertEqual(self.ledger()['entries'], [])
        self.assertEqual(self.ledger(self.other)['total'], 9)

    def test_account_erasure_also_cleans_ledger(self):
        # Use a separate identity: account erasure intentionally survives a DB reset.
        import uuid
        code = 'history-erasure-' + uuid.uuid4().hex
        owner = 'member:' + code
        with central_db() as c:
            c.execute('INSERT INTO members(code,name) VALUES(?,?)', (code, 'Проверка удаления баллов'))
            set_profile(c, owner, fixtures.GROUP)
        self.assertEqual(self.entry(self.client(code=code)).status_code, 201)
        process_one(owner, 'account')
        with central_db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM history_points WHERE owner=?', (owner,)).fetchone()[0], 0)
