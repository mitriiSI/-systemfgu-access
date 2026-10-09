"""Stable account grants, expiring recipient notes and existing reminder channels."""
import copy
import json
from datetime import datetime,timedelta
from unittest.mock import patch
import test_admin_access as fixtures
from test_group_comparison import lesson,DAY,OWN
from config import MOSCOW_TZ
from database import central_db,group_context,get_setting,owner_profile
from services import community,group_comparison as comparison,lesson_times,notification_channels
from services.admissions import set_profile

MEMBER='member:comparison-milya-account'

class ComparisonMemberFixture(fixtures.AccessFixture):
    def setUp(self):
        super().setUp()
        comparison.initialize()
        with central_db() as c:
            c.execute('DELETE FROM group_comparison_access')
            c.execute('DELETE FROM group_comparison_messages')
            c.execute("INSERT INTO members(code,name,tg) VALUES('comparison-milya-account','миля',987000112)")
            set_profile(c,MEMBER,comparison.TARGET)
            set_profile(c,self.admin_owner,OWN)
            for owner in (MEMBER,self.admin_owner):
                for row in c.execute('SELECT key FROM settings').fetchall():
                    if row[0].startswith('midiary_offsets:'+owner+':'):c.execute('DELETE FROM settings WHERE key=?',(row[0],))
        self.addCleanup(self.cleanup_access)
        comparison.grant_member(MEMBER,OWN)
        self.milya=self.client(code='comparison-milya-account')
        self.now=datetime(2026,10,19,8,45,tzinfo=MOSCOW_TZ)
        for group in (OWN,comparison.TARGET):
            from database import initialize_group
            initialize_group(group)
            with group_context(group),community.db() as c:
                lesson_times.initialize(c);lesson_times.initialize_rooms(c)
                for table in ('schedules','content','custom_lessons','hidden_lessons','lesson_times','lesson_rooms',
                              'reminder_prefs','reminder_sent','reminder_delivery','deadlines'):
                    c.execute('DELETE FROM '+table)
                raw={'date':DAY,'lessons':[lesson(),lesson('ГЕОГРАФИЯ',room='Б 301',teacher='Петров')]}
                if group==OWN:raw['lessons'][1]['periods'][0]['classroom']='Б 302'
                c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',(get_setting('group_id'),DAY,json.dumps(raw)))

    def cleanup_access(self):
        with central_db() as c:
            c.execute('DELETE FROM group_comparison_access');c.execute('DELETE FROM group_comparison_messages')
            for owner in (MEMBER,self.admin_owner):
                for row in c.execute('SELECT key FROM settings').fetchall():
                    if row[0].startswith('midiary_offsets:'+owner+':'):c.execute('DELETE FROM settings WHERE key=?',(row[0],))

class ComparisonMemberTests(ComparisonMemberFixture):
    def test_grant_follows_account_and_never_display_name(self):
        self.assertTrue(self.milya.get('/api/me').get_json()['group_comparison'])
        self.assertFalse(self.milya.get('/api/me').get_json()['group_comparison_admin'])
        with central_db() as c:
            c.execute("UPDATE members SET name='Переименован' WHERE code='comparison-milya-account'")
            c.execute("UPDATE members SET name='миля' WHERE code='existing-member'")
        self.assertEqual(self.milya.get('/api/group-comparison?date='+DAY).status_code,200)
        self.assertEqual(self.member.get('/api/group-comparison').status_code,403)
        self.assertFalse(self.member.get('/api/me').get_json()['group_comparison'])

    def test_reciprocal_comparison_keeps_membership_and_data_private(self):
        payload=comparison.snapshot(MEMBER,DAY,at=self.now)
        self.assertEqual(payload['group']['id'],OWN)
        self.assertEqual(owner_profile(MEMBER)['group_id'],comparison.TARGET)
        self.assertTrue(payload['integrated_notifications']);self.assertFalse(payload['can_message'])
        self.assertEqual(sum(l['common'] for l in payload['days'][0]['lessons']),1)
        self.assertNotIn(MEMBER,json.dumps(payload))
        self.assertEqual(comparison.watched_groups(),sorted([OWN,comparison.TARGET]))

    def test_member_can_set_own_label_but_cannot_enable_duplicate_notifications(self):
        answer=self.post(self.milya,'group-comparison',{'label':'Моя подпись'})
        self.assertEqual(answer.status_code,200)
        self.assertEqual(comparison.preferences(MEMBER)['label'],'Моя подпись')
        self.assertEqual(comparison.preferences(self.admin_owner)['label'],'')
        self.assertEqual(self.post(self.milya,'group-comparison',{'label':'X','notify_common':True}).status_code,400)
        self.assertEqual(self.milya.post('/api/group-comparison',json={'label':'X'}).status_code,403)
        self.assertEqual(comparison.candidates(MEMBER,self.now),[])

    def test_inactive_and_deleted_accounts_lose_feature(self):
        with central_db() as c:c.execute("UPDATE members SET active=0 WHERE code='comparison-milya-account'")
        self.assertFalse(comparison.allowed(MEMBER));self.assertEqual(comparison.candidates(MEMBER,self.now),[])
        with central_db() as c:c.execute("DELETE FROM members WHERE code='comparison-milya-account'")
        self.assertFalse(comparison.allowed(MEMBER));self.assertEqual(comparison.message_recipients(),[])

    def test_notes_are_primary_only_recipient_only_and_expire(self):
        recipients=self.admin.get('/api/admin/group-comparison/messages').get_json()['recipients']
        ident=recipients[0]['id'];value={'recipient':ident,'body':'<img src=x>\nВстретимся после пары','minutes':60}
        self.assertEqual(self.milya.get('/api/admin/group-comparison/messages').status_code,403)
        self.assertEqual(self.post(self.milya,'admin/group-comparison/messages',value).status_code,403)
        self.assertEqual(self.post(self.member,'admin/group-comparison/messages',value).status_code,403)
        self.assertEqual(self.admin.post('/api/admin/group-comparison/messages',json=value).status_code,403)
        import time
        stamp=time.time()
        self.assertEqual(self.post(self.admin,'admin/group-comparison/messages',value).status_code,200)
        note=self.milya.get('/api/group-comparison?date='+DAY).get_json()['note']
        self.assertEqual(set(note),{'body','expires'});self.assertAlmostEqual(note['expires'],stamp+3600,delta=2)
        self.assertIsNone(self.admin.get('/api/group-comparison?date='+DAY).get_json()['note'])
        self.assertEqual(self.milya.get('/api/account/export').get_json()['comparison_note'],note)
        self.assertIsNotNone(comparison.active_note(MEMBER,note['expires']-1))
        self.assertIsNone(comparison.active_note(MEMBER,note['expires']))
        self.assertEqual(self.post(self.admin,'admin/group-comparison/messages',value|{'body':''}).status_code,200)
        self.assertIsNone(comparison.active_note(MEMBER,1000))

    def test_note_validation_does_not_change_saved_message(self):
        ident=comparison.message_recipients()[0]['id'];value={'recipient':ident,'body':'Текст','minutes':60}
        self.post(self.admin,'admin/group-comparison/messages',value)
        for change in ({'recipient':True},{'recipient':987654},{'minutes':0},{'minutes':10081},{'minutes':True},
                       {'minutes':1.5},{'body':'x'*801},{'body':None},{'body':'x\x00y'},{'owner':'member:anyone'}):
            self.assertEqual(self.post(self.admin,'admin/group-comparison/messages',value|change).status_code,400)
        self.assertEqual(comparison.active_note(MEMBER)['body'],'Текст')

    def test_personal_deletion_erases_note_and_label_but_keeps_capability(self):
        ident=comparison.message_recipients()[0]['id']
        comparison.save_message(self.admin_owner,{'recipient':ident,'body':'Текст','minutes':60})
        comparison.save_preferences(MEMBER,{'label':'Подпись'})
        from services.privacy import process_one
        process_one(MEMBER,'personal')
        self.assertIsNone(comparison.active_note(MEMBER));self.assertTrue(comparison.allowed(MEMBER))
        self.assertEqual(comparison.preferences(MEMBER)['label'],'')

    def test_account_deletion_removes_grant_and_recipient_message(self):
        import uuid
        owner='member:comparison-delete-'+uuid.uuid4().hex
        with central_db() as c:
            c.execute('INSERT INTO members(code,name) VALUES(?,?)',(owner[7:],'Удаляемый тестовый участник'))
            set_profile(c,owner,comparison.TARGET)
        comparison.grant_member(owner,OWN)
        ident=next(r['id'] for r in comparison.message_recipients() if r['name']=='Удаляемый тестовый участник')
        comparison.save_message(self.admin_owner,{'recipient':ident,'body':'Текст','minutes':60})
        from services.privacy import process_one
        process_one(owner,'account')
        with central_db() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM group_comparison_access WHERE owner=?',(owner,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM group_comparison_messages WHERE recipient=?',(owner,)).fetchone())
        self.assertFalse(comparison.allowed(owner))

    def test_pending_account_erasure_disables_capability_immediately(self):
        with central_db() as c:
            c.execute("INSERT INTO privacy_deletions(owner,kind,created) VALUES(?,'account',0)",(MEMBER,))
        self.addCleanup(lambda:self.remove_deletion())
        self.assertFalse(comparison.allowed(MEMBER));self.assertEqual(comparison.shared_marker(MEMBER,self.now)({}),'')

    def remove_deletion(self):
        with central_db() as c:c.execute('DELETE FROM privacy_deletions WHERE owner=?',(MEMBER,))

    def test_exact_marker_only_on_shared_lessons_and_not_personal_changed_place(self):
        marker=comparison.shared_marker(MEMBER,self.now)
        with group_context(comparison.TARGET):items=comparison.entries(community.filtered_days(MEMBER),{DAY})
        self.assertEqual(marker(items[0]),'Общая пара с 107))');self.assertEqual(marker(items[1]),'')
        self.assertEqual(marker(items[0]|{'room':'Другая аудитория'}),'')
        self.assertEqual(comparison.shared_marker(self.admin_owner,self.now)(items[0]),'')

    def test_existing_telegram_max_reminders_keep_dedup_and_main_channel_preferences(self):
        from bot.worker import check_reminders
        from services.midiary import save_offsets
        with group_context(comparison.TARGET):save_offsets(MEMBER,'telegram:lessons',[15],comparison.OFFSETS)
        with patch('services.max_platform.user_for_owner',side_effect=lambda owner:876543210 if owner==MEMBER else None),\
             patch('services.delivery.tg_call') as tg,patch('services.max_platform.send_telegram') as max_send,group_context(comparison.TARGET):
            check_reminders(self.now);check_reminders(self.now+timedelta(minutes=1))
            self.assertEqual(tg.call_count,2);self.assertEqual(max_send.call_count,2)
            texts=[call.kwargs['text'] for call in tg.call_args_list]
            self.assertEqual(sum('Общая пара с 107))' in text for text in texts),1)
            self.assertTrue(all('group-comparison' not in str(call) for call in tg.call_args_list))
            with community.db() as c:c.execute('DELETE FROM reminder_sent')
            tg.reset_mock();max_send.reset_mock()
            notification_channels.save(MEMBER,{'telegram':False,'max':True,'website':True})
            check_reminders(self.now);tg.assert_not_called();self.assertEqual(max_send.call_count,2)
            with community.db() as c:c.execute('DELETE FROM reminder_sent')
            save_offsets(MEMBER,'telegram:lessons',[],comparison.OFFSETS);max_send.reset_mock();check_reminders(self.now);max_send.assert_not_called()

    def test_push_marker_uses_existing_offsets_channel_and_event_keys(self):
        from services.webpush import candidates
        prefs={'lessons':True,'deadlines':False,'lesson_minutes':15,'lesson_offsets':[15]}
        with group_context(comparison.TARGET):
            items=candidates(MEMBER,{},prefs,self.now)
            self.assertEqual(len(items),2)
            self.assertEqual(sum('Общая пара с 107))' in item[1]['body'] for item in items),1)
            self.assertTrue(all(json.loads(item[0])[0]=='lesson' for item in items))
            self.assertEqual(candidates(MEMBER,{},prefs|{'lessons':False},self.now),[])
            notification_channels.save(MEMBER,{'telegram':True,'max':True,'website':False})
            self.assertEqual(candidates(MEMBER,{},prefs,self.now),[])

    def test_exact_marker_survives_notification_translation(self):
        from services.i18n import translate_payload
        with patch('services.i18n.translate',side_effect=lambda text,lang:text.replace('Общая пара','Shared lesson').replace('Текст','Text')):
            payload=translate_payload({'text':'Текст\nОбщая пара с 107))','body':'Общая пара с 107))'},'en')
        self.assertEqual(payload['text'],'Text\nОбщая пара с 107))');self.assertEqual(payload['body'],'Общая пара с 107))')
