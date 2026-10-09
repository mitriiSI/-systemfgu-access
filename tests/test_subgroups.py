"""Assigned-group sync and personal timetable branches, without live requests."""
import copy
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from test_admin_access import AccessFixture
from database import central_db, get_db, group_context, initialize_group, set_setting, utc_now
from services import community, subgroups, timetable
from services.admissions import assign_member, set_profile,create_invitation,allow_telegram
from services.homework_reminders import tomorrow_homework
from services.webpush import single_candidates

ORIGINAL_START = timetable.start_sync
GROUP = 'fgu:1454'
OWNER = 'member:existing-member'
DAY = '2026-10-19'


def period(teacher, group='', title='Информатика', kind='Практика', start='11:25', room='101'):
    return dict(disciplineFullName=title, teachersNameFull=teacher, groups=group,
                typeStr=kind, timeStart=start, timeEnd='12:55', classroom=room)


class GroupFixture(AccessFixture):
    def setUp(self):
        super().setUp()
        initialize_group(GROUP)
        with central_db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'midiary_subgroups:%'")
            c.execute("UPDATE members SET english='',tg=800123 WHERE code='existing-member'")
            c.execute("INSERT INTO members(code,name) VALUES('second-member','Другой участник')")
            set_profile(c, OWNER, GROUP)
            set_profile(c, 'member:second-member', GROUP)
        with group_context(GROUP), community.db() as c:
            for table in ('schedules', 'hidden_lessons', 'content', 'personal', 'deadlines',
                          'custom_lessons', 'reminder_prefs', 'reminder_sent', 'reminder_delivery'):
                c.execute('DELETE FROM ' + table)
        self.other = self.client(code='second-member')
        self.raw = {'date': DAY, 'lessons': [
            {'number': 1, 'periods': [period('Общий преподаватель', kind='Лекция', start='09:00')]},
            {'number': 2, 'periods': [period('Герасименко', room='101'), period('Шевцова', room='202')]},
        ]}
        self.store(self.raw)

    def store(self, *days):
        with group_context(GROUP), community.db() as c:
            for day in days:
                c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',
                          ('1454', day['date'], json.dumps(day, ensure_ascii=False)))

    def catalog(self, client=None):
        return (client or self.member).get('/api/schedule/subgroups').get_json()['subjects']

    def choose(self, label, subject='информатика', client=None):
        entry = next(row for row in self.catalog(client) if row['subject'] == subject)
        value = next(option['id'] for option in entry['options'] if label in option['label'])
        response = self.post(client or self.member, 'schedule/subgroups', {'choices': {subject: value}})
        self.assertEqual(response.status_code, 200)
        return value

    def visible(self, client=None):
        days = (client or self.member).get('/api/schedule').get_json()['days']
        return [p for day in days for lesson in day['lessons'] for p in lesson['periods']]


class SubgroupTests(GroupFixture):
    def test_unlabelled_teacher_branches_and_common_lecture(self):
        self.raw['lessons'][0]['periods'][0]['typeStr'] = 'Lec'
        self.store(self.raw)
        self.assertEqual(len(self.catalog()[0]['options']), 2)
        self.choose('Шевцова')
        self.assertEqual([p['teachers'][0] for p in self.visible()], ['Общий преподаватель', 'Шевцова'])
        self.assertEqual(len(self.visible(self.other)), 3)
        self.assertEqual(self.member.get('/api/me').get_json()['group_id'], GROUP)

    def test_new_browser_retains_choice_and_an_explicit_clear_shows_all(self):
        self.choose('Герасименко')
        self.assertEqual(len(self.visible(self.client(code='existing-member'))), 2)
        response = self.post(self.member, 'schedule/subgroups', {'choices': {'информатика': ''}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.visible()), 3)

    def test_choice_is_scoped_to_study_group(self):
        self.choose('Герасименко')
        other_group = 'geo:subgroup-isolation'
        with central_db() as c:
            c.execute('INSERT OR REPLACE INTO university_groups VALUES(?,?,?,?,?,?,?,NULL)',
                      (other_group, 'geo', 'isolated-geo', 'География', 'Бакалавриат', 1, 'excel'))
        initialize_group(other_group)
        with group_context(other_group), community.db() as c:
            c.execute('DELETE FROM schedules')
            c.execute('INSERT INTO schedules VALUES(?,?,?)', ('isolated-geo', DAY, json.dumps(self.raw)))
        with central_db() as c:
            set_profile(c, OWNER, other_group)
        self.assertEqual(self.catalog()[0]['selected'], '')
        self.assertEqual(len(self.visible()), 3)
        with central_db() as c:
            set_profile(c, OWNER, GROUP)
        self.assertTrue(self.catalog()[0]['selected'])

    def test_explicit_subgroups_on_different_days_filter_reminder_subset(self):
        self.raw['lessons'] = [{'number': 2, 'periods': [period('Первый', '1 п/г', title='География')]}]
        other = copy.deepcopy(self.raw)
        other['date'] = '2026-10-20'
        other['lessons'][0]['periods'][0] = period('Второй', '2 п/г', title='География')
        self.store(self.raw, other)
        self.choose('2 п/г', 'география')
        with group_context(GROUP):
            one_day = community.filtered_days(OWNER, [self.raw])
        self.assertEqual(one_day[0]['lessons'], [])
        self.assertEqual([p['groups'] for p in self.visible()], ['2 п/г'])

    def test_two_teachers_on_one_period_are_one_class(self):
        self.raw['lessons'] = [{'number': 2, 'periods': [period('Первый; Второй')]}]
        self.store(self.raw)
        self.assertEqual(self.catalog(), [])
        self.assertEqual(self.visible()[0]['teachers'], ['Первый', 'Второй'])

    def test_ordinary_teacher_changes_on_different_dates_are_not_subgroups(self):
        self.raw['lessons'] = [{'number': 2, 'periods': [period('Первый')]}]
        other = copy.deepcopy(self.raw)
        other['date'] = '2026-10-26'
        other['lessons'][0]['periods'][0]['teachersNameFull'] = 'Второй'
        self.store(self.raw, other)
        self.assertEqual(self.catalog(), [])

    def test_source_teacher_id_preserves_selection_after_name_correction(self):
        for i, p in enumerate(self.raw['lessons'][1]['periods']):
            p['teacherId'] = i + 123
        self.store(self.raw)
        selected = self.choose('Герасименко')
        self.raw['lessons'][1]['periods'][0]['teachersNameFull'] = 'Герасименко — исправленное имя'
        self.store(self.raw)
        self.assertEqual(self.catalog()[0]['selected'], selected)
        self.assertIn('исправленное', self.visible()[1]['teachers'][0])

    def test_teacher_override_does_not_merge_or_change_source_branches(self):
        self.choose('Шевцова')
        response = self.post(self.member, 'schedule/teachers', {'title': 'Информатика', 'teachers': ['Редактор']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.visible()), 2)
        self.assertEqual(self.visible()[1]['classroom'], '202')
        self.assertEqual(self.catalog()[0]['options'][1]['teachers'], ['Шевцова'])

    def test_hide_only_one_branch_and_keep_it_hidden_after_sync(self):
        periods = self.visible()
        self.assertNotEqual(periods[1]['_diary_id'], periods[2]['_diary_id'])
        response = self.post(self.member, 'schedule/hide', {'id': periods[1]['_diary_id'], 'date': DAY})
        self.assertEqual(response.status_code, 200)
        self.store(self.raw)
        self.assertEqual([p['teachers'][0] for p in self.visible()], ['Общий преподаватель', 'Шевцова'])

    def test_legacy_hidden_id_still_hides_the_original_occurrence(self):
        legacy = community.lesson_id(DAY, self.raw['lessons'][1], self.raw['lessons'][1]['periods'][0])
        with group_context(GROUP), community.db() as c:
            c.execute('INSERT INTO hidden_lessons VALUES(?,?,?,?)', (OWNER, '1454', legacy, utc_now()))
        self.assertEqual(len(self.visible()), 1)

    def test_invalid_foreign_choice_csrf_and_anonymous_requests_are_rejected(self):
        for choices in ({'физика': 'missing'}, {'информатика': 'teacher:foreign'}, {'информатика': []}):
            self.assertEqual(self.post(self.member, 'schedule/subgroups', {'choices': choices}).status_code, 400)
        self.assertEqual(self.member.post('/api/schedule/subgroups', json={'choices': {}}).status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/schedule/subgroups').status_code, 401)
        self.assertEqual(self.app.test_client().get('/api/schedule').status_code, 401)

    def test_legacy_english_choice_migrates_but_can_be_cleared(self):
        self.raw['lessons'] = [{'number': 2, 'periods': [
            period('Первый', '1 п/г', title='Английский язык'),
            period('Второй', '2 п/г', title='Английский язык')]}]
        self.store(self.raw)
        with central_db() as c:
            c.execute("UPDATE members SET english='2 п/г' WHERE code='existing-member'")
        self.assertEqual([p['groups'] for p in self.visible()], ['2 п/г'])
        self.assertEqual(self.post(self.member, 'schedule/subgroups', {'choices': {'английский язык': ''}}).status_code, 200)
        self.assertEqual(len(self.visible()), 2)

    def test_push_and_homework_only_use_the_selected_branch(self):
        selected = self.choose('Шевцова')
        with group_context(GROUP), community.db() as c:
            for marker, body in [(selected, 'Задание Шевцовой'), ('', 'Старое общее задание')]:
                key = '|'.join(('105мб', DAY, '2', 'Информатика', marker))
                c.execute('INSERT INTO content VALUES(?,?,?,?,?)', ('homework', key, body, 'Автор', utc_now()))
        with group_context(GROUP):
            date, items = tomorrow_homework(OWNER, {}, datetime(2026, 10, 18, 20, tzinfo=timezone(timedelta(hours=3))))
            pushes = single_candidates(OWNER, {}, {'lessons': True, 'deadlines': False, 'lesson_minutes': 15},
                                       datetime(2026, 10, 19, 11, 10, tzinfo=timezone(timedelta(hours=3))))
        self.assertEqual(date, DAY)
        self.assertEqual(items, [('Информатика', 'Задание Шевцовой')])
        self.assertEqual(len(pushes), 1)
        self.assertIn('202', pushes[0][1]['body'])

    def test_telegram_reminders_respect_selection_without_live_delivery(self):
        self.choose('Герасименко')
        from bot.worker import check_reminders
        with group_context(GROUP), community.db() as c:
            c.execute('INSERT INTO reminder_prefs VALUES(?,15)', (OWNER,))
        with group_context(GROUP), patch('bot.worker.send_reliable_message') as send:
            check_reminders(datetime(2026, 10, 19, 11, 10, tzinfo=timezone(timedelta(hours=3))))
        self.assertEqual(send.call_count, 1)
        self.assertIn('101', send.call_args.args[2]['text'])

    def test_cleared_branch_homework_does_not_restore_legacy_homework(self):
        selected=self.choose('Шевцова')
        with group_context(GROUP),community.db() as c:
            for marker,body in [(selected,''),('','Старое ДЗ')]:
                c.execute('INSERT INTO content VALUES(?,?,?,?,?)',('homework','|'.join(('105мб',DAY,'2','Информатика',marker)),body,'Автор',utc_now()))
        with group_context(GROUP):
            _,items=tomorrow_homework(OWNER,{},datetime(2026,10,18,20,tzinfo=timezone(timedelta(hours=3))))
        self.assertEqual(items,[])

    def test_choices_export_and_personal_erasure_are_scoped_to_owner(self):
        selected=self.choose('Герасименко')
        other=self.choose('Шевцова',client=self.other)
        data=self.member.get('/api/account/export').get_json()
        self.assertEqual(data['subgroups'],{GROUP:{'информатика':selected}})
        from services.privacy import process_one
        process_one(OWNER,'personal')
        self.assertEqual(self.catalog()[0]['selected'],'')
        self.assertEqual(self.catalog(self.other)[0]['selected'],other)

    def test_older_files_and_deadlines_stay_available_inside_a_branch(self):
        selected=self.choose('Шевцова')
        legacy='|'.join(('105мб',DAY,'2','Информатика',''));item=legacy+selected
        with group_context(GROUP),community.db() as c:
            c.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?)',('legacy-file','lesson',legacy,'Конспект','notes.pdf','Автор',utc_now(),120))
            c.execute('INSERT INTO deadlines VALUES(?,?,?,?,?)',(legacy,'105мб','Информатика','2026-10-20T12:00:00+03:00',utc_now()))
        response=self.member.get('/api/lesson-detail',query_string={'item':item})
        self.assertEqual(response.status_code,200)
        data=response.get_json()
        self.assertEqual(data['files'][0]['title'],'Конспект')
        self.assertEqual(data['deadline']['item'],legacy)
        files=self.member.get('/api/files',query_string={'scope':'lesson','item':item}).get_json()
        self.assertEqual(files[0]['id'],'legacy-file')
        self.assertEqual(self.member.get('/api/lesson-detail',query_string={'item':item.replace('105мб','107пб')}).status_code,400)


class AssignedScheduleTests(GroupFixture):
    def test_invitation_and_telegram_permission_prime_the_selected_group(self):
        create_invitation(self.admin_owner,group_id=GROUP)
        self.sync_queue.assert_called_with(GROUP)
        self.sync_queue.reset_mock()
        allow_telegram(self.admin_owner,800789,group_id=GROUP)
        self.sync_queue.assert_called_with(GROUP)

    def test_assigning_a_group_queues_its_own_source_after_commit(self):
        assign_member(self.admin_owner, 'existing-member', GROUP)
        self.sync_queue.assert_called_with(GROUP)
        self.assertEqual(self.member.get('/api/me').get_json()['group_id'], GROUP)

    def test_empty_cache_is_queued_for_a_member_and_refresh_cannot_target_another_group(self):
        with group_context(GROUP), community.db() as c:
            c.execute('DELETE FROM schedules')
        response = self.member.get('/api/schedule')
        self.assertEqual(response.status_code, 200)
        self.sync_queue.assert_called_with(GROUP)
        self.assertEqual(response.get_json()['group_id'], GROUP)
        self.assertEqual(self.post(self.member, 'schedule/refresh', {'group_id': 'fgu:1457'}).status_code, 200)
        self.refresh_queue.assert_called_with(force=False)
        self.assertEqual(self.post(self.admin, 'schedule/refresh', {}).status_code, 200)
        self.refresh_queue.assert_called_with(force=True)

    def test_fgu_fetch_uses_105_source_id_and_preserves_homework_overlays(self):
        with group_context(GROUP), community.db() as c:
            c.execute('INSERT INTO content VALUES(?,?,?,?,?)', ('homework', 'existing', 'Сохранённое ДЗ', 'Автор', utc_now()))
        def response(url, json, timeout):
            data = dict(self.raw, date=json['dateStart'])
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [data])
        with patch('services.timetable.requests.post', side_effect=response) as fetch:
            self.assertTrue(timetable.sync_schedule(GROUP))
        self.assertTrue(fetch.call_count > 1)
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, {'https://my.spa.msu.ru/api/web/timetable/group'})
        self.assertEqual({call.kwargs['json']['groupId'] for call in fetch.call_args_list}, {'1454'})
        with group_context(GROUP), community.db() as c:
            self.assertEqual(c.execute("SELECT body FROM content WHERE item='existing'").fetchone()[0], 'Сохранённое ДЗ')
            self.assertTrue(c.execute("SELECT value FROM settings WHERE key='sync_1454'").fetchone()[0])

    def test_source_failure_preserves_the_existing_schedule(self):
        with patch('services.timetable.requests.post', side_effect=TimeoutError):
            self.assertFalse(timetable.sync_schedule(GROUP))
        self.assertEqual(len(self.visible()), 3)

    def test_fresh_cache_does_not_fetch_and_stale_cache_can_recover(self):
        with group_context(GROUP):
            set_setting('sync_1454', utc_now())
            self.sync_queue.reset_mock()
            timetable.ensure_schedule(has_cache=True)
            self.sync_queue.assert_not_called()
            set_setting('sync_1454', '2020-01-01T00:00:00+00:00')
            timetable.ensure_schedule(has_cache=True)
            self.sync_queue.assert_called_with(GROUP)

    def test_queue_deduplicates_and_limits_member_refreshes(self):
        with patch('services.timetable._queued', set()), patch.dict(timetable._attempts, {}, clear=True), \
             patch.dict(timetable._locks, {}, clear=True), patch('services.timetable.threading.Thread') as thread, \
             patch('services.timetable.sync_schedule', return_value=True):
            self.assertTrue(ORIGINAL_START(GROUP))
            self.assertTrue(ORIGINAL_START(GROUP))
            self.assertEqual(thread.call_count, 1)
            thread.call_args.kwargs['target']()
            self.assertFalse(ORIGINAL_START(GROUP))
            self.assertTrue(ORIGINAL_START(GROUP, force=True))
            self.assertEqual(thread.call_count, 2)
            thread.call_args.kwargs['target']()

    def test_faculty_catalogue_hides_history_and_has_offline_faculties(self):
        rows = self.app.test_client().get('/api/faculties').get_json()
        self.assertEqual([row['id'] for row in rows], ['fgu', 'geo', 'ffl', 'fgp'])
        self.assertEqual(rows[2]['name'], 'Факультет иностранных языков и регионоведения')
        with patch('requests.get', side_effect=AssertionError('Catalogues must be offline')):
            response = self.app.test_client().get('/api/groups?faculty=ffl')
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.get_json()), 50)
        self.assertEqual({row['source'] for row in response.get_json()}, {'excel'})
