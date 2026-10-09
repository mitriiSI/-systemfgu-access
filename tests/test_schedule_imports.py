"""Actual timetable files: merged cells, parity, private imports and no network."""
import io
import json
from pathlib import Path
from unittest.mock import patch

from test_admin_access import AccessFixture
from database import central_db, group_context, initialize_group, get_setting
from services import community
from services.admissions import set_profile
from services.table_schedules import preview_table, catalogue, Cell, Grid

FIXTURES = Path(__file__).parent / 'fixtures'


class TimetableFilesTests(AccessFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pdf = (FIXTURES / 'fgp-first-course.pdf').read_bytes()
        cls.parsed = preview_table(cls.pdf, 'fgp.pdf', {}, '101')

    def setUp(self):
        super().setUp()
        initialize_group('fgp:101')
        with central_db() as c:
            set_profile(c, 'member:existing-member', 'fgp:101')
            set_profile(c, self.admin_owner, 'fgp:101')
            c.execute("INSERT INTO members(code,name) VALUES('import-other','Другой студент')")
            set_profile(c, 'member:import-other', 'fgp:101')
        with group_context('fgp:101'), community.db() as c:
            for table in ('schedules', 'custom_lessons', 'schedule_imports', 'hidden_lessons', 'content'):
                c.execute('DELETE FROM ' + table)
            c.execute("DELETE FROM settings WHERE key LIKE 'personal_import:%'")
            c.execute("DELETE FROM settings WHERE key LIKE 'midiary_import_choices:%'")
        self.other = self.client(code='import-other')

    def token(self,owner='member:existing-member'):
        payload = [row for row in self.parsed['rows'] if row['title'] == 'Безопасность жизнедеятельности']
        from time import time
        with group_context('fgp:101'), community.db() as c:
            c.execute('INSERT INTO schedule_imports VALUES(?,?,?,?,?,?,0,0)',
                      ('preview-token', owner, time(), time() + 1800, json.dumps(payload), 'fgp.pdf'))
        return 'preview-token', payload

    def test_pdf_cells_merged_for_some_groups_only(self):
        self.assertFalse(self.parsed['errors'])
        safety = [row for row in self.parsed['templates'] if row['title'] == 'Безопасность жизнедеятельности']
        self.assertEqual(len(safety), 1)
        self.assertEqual((safety[0]['weekday'], safety[0]['teacher'], safety[0]['room']), (0, 'Коринный Д.В.', '440'))
        other = preview_table(self.pdf, 'fgp.pdf', {}, '106')
        self.assertFalse(any(row['title'] == 'Безопасность жизнедеятельности' and row['weekday'] == 0 for row in other['templates']))

    def test_odd_even_weeks_and_subgroups_are_independent(self):
        odd = [row for row in self.parsed['rows'] if row['week'] == 'odd' and row['weekday'] == 2]
        even = [row for row in self.parsed['rows'] if row['week'] == 'even' and row['weekday'] == 2]
        self.assertTrue(odd and even)
        self.assertIn('2026-09-02', {row['date'] for row in odd})
        self.assertNotIn('2026-09-09', {row['date'] for row in odd})
        self.assertIn('2026-09-09', {row['date'] for row in even})
        english = [row for row in self.parsed['templates'] if row['title'] == 'Английский язык']
        self.assertEqual(len({row['group'] for row in english}), 10)

    def test_explicit_time_inside_a_cell_overrides_the_pair_grid(self):
        geography = [row for row in self.parsed['templates'] if row['title'] == 'Глобальная география']
        self.assertTrue(geography)
        self.assertEqual((geography[0]['start'], geography[0]['end']), ('15:00', '16:15'))

    def test_split_pdf_thursday_first_pair_is_not_added_to_wednesday(self):
        english=[row for row in self.parsed['templates'] if row['title']=='Английский язык']
        self.assertEqual({(row['weekday'],row['number']) for row in english},{(1,1),(1,2),(3,1),(3,2)})
        # Both consecutive Tuesday language classes really exist in the PDF.
        tuesday=[row for row in self.parsed['rows'] if row['date']=='2026-10-06' and row['title']=='Английский язык' and row['group']=='Группа 1']
        self.assertEqual({(row['start'],row['end']) for row in tuesday},{('09:00','10:30'),('10:45','12:15')})

    def test_explicit_interval_in_vertically_merged_cell_is_imported_once(self):
        grid=Grid([Cell(0,0,20,100,'Понедельник'),Cell(20,0,40,50,'1 пара 09:00-10:30'),
                   Cell(20,50,40,100,'2 пара 10:45-12:15'),Cell(40,-10,100,0,'101'),
                   Cell(40,0,100,100,'(09:15-10:00) Физика Лк, ауд.100, пр. Иванов И.И.')])
        with patch('services.table_schedules.read_grids',return_value=[grid]):
            parsed=preview_table(b'fixture','merged.pdf',{'from':'2026-10-05','to':'2026-10-05'},'101')
        self.assertFalse(parsed['errors'])
        self.assertEqual(len(parsed['rows']),1)
        self.assertEqual((parsed['rows'][0]['start'],parsed['rows'][0]['end']),('09:15','10:00'))

    def test_ffl_numbered_pair_uses_local_bell_times_without_network(self):
        from services.bell_times import for_group
        times=for_group({'faculty':'ffl','level':'Магистратура'})
        grid=Grid([Cell(0,0,20,10,'День'),Cell(20,0,40,10,'Время'),Cell(40,0,100,10,'101'),
                   Cell(0,10,20,50,'Понедельник'),Cell(20,10,40,50,'6 пара'),Cell(40,10,100,50,'Лингвистика Лк')])
        with patch('services.table_schedules.read_grids',return_value=[grid]),patch('requests.get',side_effect=AssertionError('External fetch')):
            parsed=preview_table(b'fixture','photo.jpg',{'from':'2026-10-05','to':'2026-10-05','bell_times':times},'101')
        self.assertFalse(parsed['errors'])
        self.assertEqual((parsed['rows'][0]['number'],parsed['rows'][0]['start'],parsed['rows'][0]['end']),(6,'18:15','19:45'))

    def test_private_import_rejects_multiple_languages_in_one_row(self):
        from routes.imports import reviewed_entries
        entries=[row for row in self.parsed['rows'] if row['date']=='2026-10-06' and row['number']==1 and row['group']=='Группа 1']
        self.assertEqual(len(entries),2)
        with self.assertRaisesRegex(ValueError,'один предмет'):reviewed_entries(entries,{},personal=True)

    def test_time_under_gear_is_private_and_can_be_restored(self):
        token,_=self.token(self.admin_owner);self.post(self.admin,'schedule/import/commit',{'token':token,'visibility':'group'})
        day='2026-10-05'
        before=self.member.get('/api/schedule').get_json()['days']
        period=next(p for d in before if d['date']==day for l in d['lessons'] for p in l['periods'])
        result=self.post(self.member,'schedule/time',{'id':period['_diary_id'],'date':day,'start':'09:15','end':'10:45'})
        self.assertEqual(result.status_code,200)
        def times(client):
            return [(p['timeStart'],p['timeEnd']) for d in client.get('/api/schedule').get_json()['days'] if d['date']==day for l in d['lessons'] for p in l['periods']]
        self.assertEqual(times(self.member),[('09:15','10:45')])
        self.assertEqual(times(self.other),[('09:00','10:30')])
        self.assertEqual(self.post(self.member,'schedule/time',{'id':period['_diary_id'],'date':day,'restore':True}).status_code,200)
        self.assertEqual(times(self.member),[('09:00','10:30')])

    def test_imported_personal_pair_time_cannot_be_changed_by_another_member(self):
        token,_=self.token();self.post(self.member,'schedule/import/commit',{'token':token})
        day='2026-10-05';query='/api/schedule/events?start='+day+'&end='+day
        event=self.member.get(query).get_json()[0]
        body={'id':event['occurrence_id'],'date':day,'start':'09:20','end':'10:50'}
        self.assertEqual(self.post(self.other,'schedule/time',body).status_code,404)
        self.assertEqual(self.post(self.member,'schedule/time',body).status_code,200)
        self.assertEqual(self.member.get(query).get_json()[0]['start'],'09:20')
        self.assertEqual(self.post(self.member,'schedule/time',body|{'end':'08:00'}).status_code,400)

    def test_saved_language_alternatives_require_a_personal_choice_and_keep_original_data(self):
        day='2026-10-06';query='/api/schedule/events?start='+day+'&end='+day
        with group_context('fgp:101'),community.db() as c:
            for ident,title in (('a'*32,'Английский язык'),('b'*32,'Русский язык как иностранный')):
                data={'date':day,'start':'09:00','end':'10:30','number':1,'title':title,'group':'Группа 1','type':'lesson','recurrence':'once','_schedule_import':'previous','choice':'primary-language'}
                c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',(ident,'member:existing-member',get_setting('group_id'),json.dumps(data)))
        self.assertEqual(self.member.get(query).get_json(),[])
        choices=self.member.get('/api/schedule/import/choices').get_json()
        self.assertTrue(choices['available']);self.assertTrue(choices['unresolved'])
        self.assertEqual(self.post(self.member,'schedule/import/choices',{'choices':{'primary-language':'Английский язык'}}).status_code,200)
        self.assertEqual([event['title'] for event in self.member.get(query).get_json()],['Английский язык'])
        self.assertFalse(self.other.get('/api/schedule/import/choices').get_json()['available'])
        with group_context('fgp:101'):
            self.assertEqual([event['title'] for event in community.events('member:existing-member',day,day)],['Английский язык'])
            with community.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM custom_lessons WHERE active=1').fetchone()[0],2)
        self.assertEqual(self.post(self.member,'schedule/import/choices',{'choices':{'primary-language':'Русский язык как иностранный'}}).status_code,200)
        self.assertEqual([event['title'] for event in self.member.get(query).get_json()],['Русский язык как иностранный'])

    def test_unknown_saved_import_choices_are_rejected(self):
        response=self.post(self.member,'schedule/import/choices',{'choices':{'unknown':'Физика'}})
        self.assertEqual(response.status_code,400)

    def test_pdf_continuation_recovers_split_day_and_language_subgroups(self):
        data = (FIXTURES / 'fgp-masters-continuation.pdf').read_bytes()
        parsed = preview_table(data, 'masters.pdf', {}, '614моги')
        self.assertFalse(parsed['errors'])
        science = [row for row in parsed['templates'] if row['title'] == 'Philosophy and History of Science']
        self.assertEqual({row['weekday'] for row in science}, {5})
        self.assertEqual({row['type'] for row in science}, {'Лекция', 'Семинар'})
        self.assertTrue(any(row['page'] == 2 and row['week'] == 'even' for row in science))
        dates = {row['date'] for row in parsed['rows'] if row['title'] == 'Philosophy and History of Science' and row['type'] == 'Семинар'}
        self.assertIn('2026-10-10', dates)
        self.assertNotIn('2026-10-03', dates)
        self.assertFalse(any(day < '2026-10-03' for day in dates))
        other = preview_table(data, 'masters.pdf', {}, '615игпп_ин')
        english = [row for row in other['templates'] if row['title'] == 'Профессиональный английский язык']
        self.assertEqual({row['group'] for row in english}, {'Группа 1', 'Группа 2', 'Группа 3', 'Группа 4', 'Группа 7'})
        self.assertTrue(any(row['teacher'] == 'Добросклонская Е.Н.' for row in english))
        research = [row['date'] for row in other['rows'] if row['title'] == 'НИС "Актуальные проблемы глобалистики"']
        self.assertEqual(research, ['2026-09-30', '2026-10-28', '2026-11-25'])

    def test_word_headers_and_language_variants(self):
        data = (FIXTURES / 'ffl-regional-first-course.docx').read_bytes()
        self.assertEqual(catalogue(data, 'ffl.docx'), ['101', '102', '103'])
        parsed = preview_table(data, 'ffl.docx', {'from': '2026-09-01', 'to': '2026-09-07'}, '101')
        self.assertFalse(parsed['errors'])
        self.assertTrue(any(row['teacher'] == 'Павловская А.В.' for row in parsed['rows']))
        languages = [row for row in parsed['templates'] if row['title'] == 'Второй иностранный язык']
        self.assertGreaterEqual(len({row['group'] for row in languages}), 3)

    def test_preview_runs_without_fetching_any_source(self):
        with patch('requests.get', side_effect=AssertionError('External fetch')), patch('requests.post', side_effect=AssertionError('External fetch')):
            response = self.member.post('/api/schedule/import/preview', data={'file': (io.BytesIO(self.pdf), 'fgp.pdf'), 'options': '{}'}, headers={'X-CSRF-Token': 'test-csrf'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.get_json())

    def test_private_import_is_reviewed_and_invisible_to_other_member(self):
        token, entries = self.token()
        ident = entries[0]['template_id']
        response = self.post(self.member, 'schedule/import/commit', {'token': token, 'edits': {ident: {'title': 'Исправленная пара', 'room': '999'}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['visibility'], 'personal')
        query = '/api/schedule/events?start=2026-09-01&end=2026-12-31'
        own = self.member.get(query).get_json()
        self.assertTrue(own)
        self.assertEqual({row['title'] for row in own}, {'Исправленная пара'})
        self.assertEqual({row['room'] for row in own}, {'999'})
        self.assertEqual(self.other.get(query).get_json(), [])
        self.assertEqual(self.member.get('/api/schedule').get_json()['days'], [])
        again = self.post(self.member, 'schedule/import/commit', {'token': token})
        self.assertEqual(again.get_json()['added'], response.get_json()['added'])

    def test_shared_import_and_token_ownership(self):
        token, _ = self.token(self.admin_owner)
        self.assertEqual(self.post(self.other, 'schedule/import/commit', {'token': token}).status_code, 409)
        self.assertEqual(self.post(self.member,'schedule/import/commit',{'token':token,'visibility':'group'}).status_code,403)
        response = self.post(self.admin, 'schedule/import/commit', {'token': token, 'visibility': 'group'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.other.get('/api/schedule').get_json()['days'])

    def test_invalid_edit_leaves_timetable_empty(self):
        token, entries = self.token()
        response = self.post(self.member, 'schedule/import/commit', {'token': token, 'edits': {entries[0]['template_id']: {'start': '14:00', 'end': '09:00'}}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.member.get('/api/schedule/events?start=2026-09-01&end=2026-12-31').get_json(), [])

    def test_member_selects_new_faculty_without_external_sync(self):
        with patch('requests.get', side_effect=AssertionError('External fetch')), patch('requests.post', side_effect=AssertionError('External fetch')):
            result = self.post(self.member, 'study-group', {'faculty': 'ffl', 'group': self.app.test_client().get('/api/groups?faculty=ffl').get_json()[0]['id']})
            self.assertEqual(result.status_code, 200)
            data = self.member.get('/api/schedule').get_json()
        self.assertFalse(data['days'])
        self.assertFalse(data['syncing'])

    def test_missing_group_can_be_named_and_is_stored_locally(self):
        result = self.post(self.member, 'study-group', {'faculty':'ffl', 'group_name':'К-201', 'level':'Бакалавриат', 'course':2, 'program':'Культурология'})
        self.assertEqual(result.status_code,200)
        me = self.member.get('/api/me').get_json()
        self.assertEqual((me['faculty'],me['group']),('ffl','К-201'))
        self.assertTrue(any(row['id']==me['group_id'] for row in self.other.get('/api/groups?faculty=ffl').get_json()))

    def test_registration_requests_faculty_choice_on_first_visit(self):
        client=self.app.test_client()
        self.assertEqual(self.register(self.code(),client).status_code,200)
        self.assertTrue(client.get('/api/me').get_json()['choose_study_group'])
        me=client.get('/api/me').get_json()
        self.assertEqual(client.post('/api/study-group',json={'faculty':'fgp','group':'fgp:101'},headers={'X-CSRF-Token':me['csrf']}).status_code,200)
        self.assertFalse(client.get('/api/me').get_json()['choose_study_group'])
