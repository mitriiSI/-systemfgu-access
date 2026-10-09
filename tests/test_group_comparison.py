"""Private comparison permissions, schedule isolation and notification delivery."""
import copy
import json
from datetime import datetime,timedelta,date
from unittest.mock import patch
import test_admin_access as fixtures
from config import PRIMARY_ADMIN_ID,MOSCOW_TZ
from database import central_db,central_setting,get_setting,group_context,current_group,initialize_group
from services import group_comparison as comparison,community,lesson_times,notification_channels
from services.admissions import set_profile

OWN='fgu:1457'
DAY='2026-10-19'

def lesson(title='ИСТОРИЯ РОССИИ',start='09:00',end='10:30',room='Е 740',teacher='Иванов Иван Иванович'):
    return {'number':1,'periods':[dict(disciplineFullName=title,timeStart=start,timeEnd=end,
            classroom=room,teachersNameFull=teacher,typeStr='Лекция',groups='')]}

class GroupComparisonTests(fixtures.AccessFixture):
    def setUp(self):
        super().setUp()
        initialize_group(comparison.TARGET);initialize_group(OWN)
        with central_db() as c:
            set_profile(c,self.admin_owner,OWN)
            c.execute('DELETE FROM settings WHERE key=?',(comparison.pref_key(self.admin_owner),))
            c.execute('DELETE FROM settings WHERE key=?',('midiary_offsets:'+self.admin_owner+':notification-channels',))
        self.addCleanup(self.clear_preferences)
        for group in (OWN,comparison.TARGET):
            with group_context(group),community.db() as c:
                lesson_times.initialize(c);lesson_times.initialize_rooms(c)
                for table in ('schedules','content','custom_lessons','hidden_lessons','lesson_times','lesson_rooms',
                              'reminder_prefs','reminder_sent','reminder_delivery','deadlines'):
                    c.execute('DELETE FROM '+table)
        self.raw={'date':DAY,'lessons':[lesson()]}
        self.store(OWN,self.raw)
        target=copy.deepcopy(self.raw)
        target['lessons'] += [lesson('ГЕОГРАФИЯ',start='11:00',end='12:30',room='Б 301',teacher='Петров'),
                              lesson('ИСТОРИЯ РОССИИ',room='Е 741')]
        self.store(comparison.TARGET,target)
        self.now=datetime(2026,10,19,8,45,tzinfo=MOSCOW_TZ)

    def clear_preferences(self):
        with central_db() as c:
            c.execute('DELETE FROM settings WHERE key=?',(comparison.pref_key(self.admin_owner),))
            c.execute('DELETE FROM settings WHERE key=?',('midiary_offsets:'+self.admin_owner+':notification-channels',))

    def store(self,group,*days):
        with group_context(group),community.db() as c:
            for day in days:
                c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',
                          (get_setting('group_id'),day['date'],json.dumps(day,ensure_ascii=False)))

    def snapshot(self,**options):
        return comparison.snapshot(self.admin_owner,DAY,at=self.now,**options)

    def prefs(self,**values):
        return comparison.save_preferences(self.admin_owner,comparison.preferences(self.admin_owner)|values)

    def test_only_primary_admin_can_access_even_if_another_admin_exists(self):
        url='/api/admin/group-comparison?date='+DAY
        self.assertEqual(self.app.test_client().get(url).status_code,401)
        self.assertEqual(self.member.get(url).status_code,403)
        self.assertFalse(self.member.get('/api/me').get_json()['group_comparison'])
        self.assertTrue(self.admin.get('/api/me').get_json()['group_comparison'])
        self.assertEqual(self.admin.get(url).status_code,200)
        other_id=987123
        with patch('routes.auth.ADMINS',{PRIMARY_ADMIN_ID,other_id}):
            other=self.client(tg=other_id)
            self.assertFalse(other.get('/api/me').get_json()['group_comparison'])
            self.assertEqual(other.get(url).status_code,403)
            self.assertEqual(self.post(other,'admin/group-comparison',comparison.preferences(self.admin_owner)).status_code,403)

    def test_comparison_requires_matching_place_or_teacher_and_keeps_all_day_classes(self):
        result=self.snapshot();items=result['days'][0]['lessons']
        self.assertEqual(len(items),3)
        self.assertEqual([l['room'] for l in result['today_common']],['Е 740'])
        self.assertEqual(items[0]['title'],'История россии')
        self.assertEqual(result['next']['start'],'09:00')
        live=comparison.snapshot(self.admin_owner,DAY,at=self.now+timedelta(minutes=20))
        self.assertEqual(len(live['current']),2)
        a=items[0];b=copy.deepcopy(a)
        for changes in ({'room':'Е 741'},{'teachers':['Другой']},{'start':'09:05'},{'title':'География'}):
            self.assertFalse(comparison.shared(a,b|changes))
        self.assertFalse(comparison.shared(a|{'room':'','teachers':[]},b|{'room':'','teachers':[]}))

    def test_snapshot_whitelist_does_not_read_target_private_overlays_files_or_homework(self):
        raw=copy.deepcopy(self.raw)
        raw['lessons'][0]['periods'][0].update(homework='secret-homework',files=['secret-file'])
        self.store(comparison.TARGET,raw)
        with group_context(comparison.TARGET),community.db() as c:
            ident=community.filtered_days('member:target')[0]['lessons'][0]['periods'][0]['_diary_id']
            c.execute('INSERT INTO lesson_rooms VALUES(?,?,?,?)',('member:target',get_setting('group_id'),ident,'secret-private-room'))
            c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',('e'*32,'member:target',get_setting('group_id'),
                      json.dumps({'date':DAY,'start':'09:00','end':'10:30','title':'secret-event','type':'lesson'})))
            c.execute('INSERT OR REPLACE INTO content VALUES(?,?,?,?,?)',('homework','secret-item','secret-homework','private-person','now'))
        value=self.snapshot();serialized=json.dumps(value)
        for text in ('secret-','private-person','member:target','_diary_id'):self.assertNotIn(text,serialized)
        allowed={'date','number','title','start','end','room','teachers','type','common'}
        self.assertEqual(set(value['days'][0]['lessons'][0]),allowed)

    def test_own_time_room_and_hidden_changes_affect_shared_match_without_changing_target(self):
        with group_context(OWN):
            ident=community.filtered_days(self.admin_owner)[0]['lessons'][0]['periods'][0]['_diary_id']
            with community.db() as c:
                c.execute('INSERT INTO lesson_times VALUES(?,?,?,?,?)',(self.admin_owner,get_setting('group_id'),ident,'09:05','10:35'))
        self.assertEqual(self.snapshot()['today_common'],[])
        with group_context(OWN),community.db() as c:c.execute('DELETE FROM lesson_times')
        self.assertEqual(len(self.snapshot()['today_common']),1)
        with group_context(OWN),community.db() as c:
            c.execute('INSERT INTO hidden_lessons VALUES(?,?,?,?)',(self.admin_owner,get_setting('group_id'),ident,'now'))
        self.assertEqual(self.snapshot()['today_common'],[])
        self.assertEqual(self.snapshot()['days'][0]['lessons'][0]['start'],'09:00')

    def test_week_range_and_group_context_are_preserved(self):
        with group_context(OWN):
            result=comparison.snapshot(self.admin_owner,'2027-01-01',week=True,at=self.now)
            self.assertEqual(current_group(),OWN)
        self.assertEqual([d['date'] for d in result['days']],[(date(2026,12,28)+timedelta(days=i)).isoformat() for i in range(7)])
        self.assertEqual(len(result['today_common']),1)

    def test_duplicate_source_branches_are_collapsed(self):
        raw=copy.deepcopy(self.raw);raw['lessons'].append(copy.deepcopy(raw['lessons'][0]))
        self.store(comparison.TARGET,raw)
        self.assertEqual(len(self.snapshot()['days'][0]['lessons']),1)

    def test_inputs_are_validated_and_csrf_is_required(self):
        for query in ('date=0001-01-01','date=9999-12-31','date=2026-13-01','date=20261019','week=yes'):
            self.assertEqual(self.admin.get('/api/admin/group-comparison?'+query).status_code,400)
        prefs=comparison.preferences(self.admin_owner)
        self.assertEqual(self.admin.post('/api/admin/group-comparison',json=prefs).status_code,403)
        for changes in ({'label':'x'*61},{'label':'bad\nlabel'},{'notify_common':1},{'offsets':[True]},
                        {'offsets':[16]},{'channels':{}},{'unexpected':'value'},
                        {'notify_common':True,'offsets':[]}):
            self.assertEqual(self.post(self.admin,'admin/group-comparison',prefs|changes).status_code,400)
        self.assertFalse(self.snapshot()['preferences']['notify_common'])

    def test_label_and_preferences_are_private_exportable_and_erased(self):
        result=self.post(self.admin,'admin/group-comparison',comparison.preferences(self.admin_owner)|{'label':'Моя подпись'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.snapshot()['preferences']['label'],'Моя подпись')
        self.assertEqual(self.admin.get('/api/account/export').get_json()['notifications']['group_comparison']['label'],'Моя подпись')
        self.assertNotIn('group_comparison',self.member.get('/api/account/export').get_json()['notifications'])
        from services.privacy import process_one
        process_one(self.admin_owner,'personal')
        self.assertEqual(central_setting(comparison.pref_key(self.admin_owner)),'')

    def test_reminders_default_off_and_enabled_scope_uses_custom_label_and_offsets(self):
        self.assertEqual(comparison.candidates(self.admin_owner,self.now),[])
        self.prefs(notify_common=True,label='Моя подпись',offsets=[15,15])
        items=comparison.candidates(self.admin_owner,self.now)
        self.assertEqual(len(items),1)
        self.assertIn('У Моя подпись пара:',items[0]['body']);self.assertIn('У вас общая пара.',items[0]['body'])
        self.assertEqual(items,comparison.candidates(self.admin_owner,self.now+timedelta(minutes=1)))
        self.assertEqual(comparison.candidates(self.admin_owner,self.now+timedelta(minutes=3)),[])
        self.assertEqual(comparison.candidates('member:existing-member',self.now),[])
        self.prefs(notify_common=False,notify_other=True)
        other=comparison.candidates(self.admin_owner,self.now)
        self.assertEqual(len(other),1);self.assertNotIn('У вас общая пара.',other[0]['body'])

    def test_bot_delivery_uses_selected_channels_and_existing_durable_deduplication(self):
        from bot.worker import check_reminders
        self.prefs(notify_common=True,channels={'telegram':True,'max':False,'website':False})
        with group_context(OWN),patch('services.delivery.tg_call') as tg,patch('services.max_platform.send_telegram') as max_send:
            check_reminders(self.now);check_reminders(self.now+timedelta(minutes=1))
            self.assertEqual(tg.call_count,1);max_send.assert_not_called()
            self.assertIn('Общая пара',tg.call_args.kwargs['text'])

    def test_website_delivery_requires_both_comparison_and_account_channel(self):
        from services.webpush import candidates
        self.prefs(notify_common=True,channels={'telegram':False,'max':False,'website':True})
        prefs={'lessons':False,'deadlines':False}
        with group_context(OWN):
            items=candidates(self.admin_owner,{},prefs,self.now)
            self.assertEqual(len(items),1);self.assertIn('compare=1',items[0][1]['url'])
            notification_channels.save(self.admin_owner,{'telegram':True,'max':True,'website':False})
            self.assertEqual(candidates(self.admin_owner,{},prefs,self.now),[])

    def test_max_delivery_can_be_selected_independently(self):
        from bot.worker import check_reminders
        self.prefs(notify_common=True,channels={'telegram':False,'max':True,'website':False})
        with group_context(OWN),patch('services.max_platform.user_for_owner',return_value=900123),\
             patch('services.delivery.tg_call') as tg,patch('services.max_platform.send_telegram') as max_send:
            check_reminders(self.now);check_reminders(self.now+timedelta(minutes=1))
            tg.assert_not_called();self.assertEqual(max_send.call_count,1)
            self.assertEqual(max_send.call_args.kwargs['owner'],self.admin_owner)

    def test_blank_label_never_inserts_group_name_into_notifications(self):
        self.prefs(notify_common=True,notify_other=True)
        items=comparison.candidates(self.admin_owner,self.now)
        self.assertEqual(len(items),2)
        for item in items:
            self.assertNotIn('105',item['body']+item['title'])
            self.assertTrue(item['body'].startswith('Пара:'))

    def test_comparison_failure_does_not_abort_existing_reminder_worker(self):
        from bot.worker import check_reminders
        with group_context(OWN),patch('services.group_comparison.candidates',side_effect=ValueError('Invalid cache')),\
             patch('bot.worker._error_details') as report:
            result=check_reminders(self.now)
            self.assertGreater(result['errors'],0);report.assert_called()

    def test_target_is_synced_without_giving_membership_or_material_access(self):
        from services import timetable
        self.assertEqual(comparison.watched_groups(),[comparison.TARGET])
        with patch('services.timetable.active_groups',return_value=[OWN]),patch('services.timetable.sync_schedule',return_value=True) as sync:
            self.assertTrue(timetable.sync_all_schedules())
            self.assertEqual([call.args[0] for call in sync.call_args_list],[OWN,comparison.TARGET])
        from database import owner_profile
        self.assertEqual(owner_profile(self.admin_owner)['group_id'],OWN)
