"""Reciprocal windows mirror the selected person's lessons, never their files."""
import json
import test_comparison_member as member_fixtures
from test_group_comparison import lesson,DAY,OWN
from database import central_db,group_context,get_setting,owner_profile,initialize_group
from services import community,group_comparison as comparison,subgroups
from services.admissions import set_profile
from services.teachers import subject_key

MEMBER=member_fixtures.MEMBER

class PersonalComparisonTests(member_fixtures.ComparisonMemberFixture):
    def setUp(self):
        super().setUp()
        comparison.bind_pair(MEMBER)
        self.addCleanup(self.clear_subgroups)

    def clear_subgroups(self):
        with central_db() as c:
            for owner in (MEMBER,self.admin_owner):
                for row in c.execute('SELECT key FROM settings').fetchall():
                    if row[0].startswith('midiary_subgroups:'+owner+':'):c.execute('DELETE FROM settings WHERE key=?',(row[0],))

    def store(self,group,raw):
        with group_context(group),community.db() as c:
            c.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?)',(get_setting('group_id'),raw['date'],json.dumps(raw)))

    def branched(self,group):
        raw={'date':DAY,'lessons':[lesson()]}
        for i,teacher in ((1,'Первый преподаватель'),(2,'Второй преподаватель')):
            part=lesson('Английский язык',start='11:00',end='12:30',room=str(600+i),teacher=teacher)
            part['number']=2;part['periods'][0].update(groups=str(i)+' п/г',typeStr='Практика')
            raw['lessons'].append(part)
        self.store(group,raw)

    def choose(self,owner,group,label):
        with group_context(group):
            raw=community.official_days();subject=subject_key('Английский язык')
            info=subgroups.describe(raw)[subject]
            chosen=next(option['id'] for option in info['options'].values() if option['group']==label)
            subgroups.save_choices(owner,raw,{subject:chosen})

    def own_records(self,owner,group):
        with group_context(group):return comparison.personal_entries(owner,{DAY})

    def seen_records(self,viewer):
        payload=comparison.snapshot(viewer,DAY,at=self.now)
        return [{k:v for k,v in item.items() if k!='common'} for item in payload['days'][0]['lessons']]

    def assert_same(self,seen,expected):
        key=lambda item:(item['date'],item['start'],item['title'],item['room'])
        self.assertEqual(sorted(seen,key=key),sorted(expected,key=key))

    def test_admin_window_uses_milya_selected_subgroup_and_updates_after_change(self):
        self.branched(comparison.TARGET)
        # The viewer's own preferences must not override the counterpart's choice.
        self.choose(self.admin_owner,comparison.TARGET,'1 п/г')
        self.choose(MEMBER,comparison.TARGET,'2 п/г')
        items=self.seen_records(self.admin_owner)
        self.assert_same(items,self.own_records(MEMBER,comparison.TARGET))
        english=next(item for item in items if item['title']=='Английский язык')
        self.assertEqual(english['room'],'602');self.assertEqual(english['teachers'],['Второй преподаватель'])
        self.choose(MEMBER,comparison.TARGET,'1 п/г')
        english=next(item for item in self.seen_records(self.admin_owner) if item['title']=='Английский язык')
        self.assertEqual(english['room'],'601')

    def test_member_window_uses_administrator_selected_subgroup(self):
        self.branched(OWN);self.choose(self.admin_owner,OWN,'1 п/г');self.choose(MEMBER,OWN,'2 п/г')
        items=self.seen_records(MEMBER)
        self.assert_same(items,self.own_records(self.admin_owner,OWN))
        self.assertEqual(next(item for item in items if item['title']=='Английский язык')['room'],'601')

    def test_legacy_english_choice_and_common_lecture_are_preserved(self):
        self.branched(comparison.TARGET)
        with central_db() as c:c.execute('UPDATE members SET english=? WHERE code=?',('2 п/г',MEMBER[7:]))
        items=self.seen_records(self.admin_owner)
        self.assertEqual([item['room'] for item in items],['Е 740','602'])
        self.assert_same(items,self.own_records(MEMBER,comparison.TARGET))

    def test_time_room_hidden_and_personal_lesson_changes_mirror_in_both_directions(self):
        for owner,group,viewer in ((MEMBER,comparison.TARGET,self.admin_owner),(self.admin_owner,OWN,MEMBER)):
            with group_context(group),community.db() as c:
                raw=community.filtered_days(owner)[0];one,two=raw['lessons']
                ident=one['periods'][0]['_diary_id'];hidden=two['periods'][0]['_diary_id']
                c.execute('INSERT INTO lesson_times VALUES(?,?,?,?,?)',(owner,get_setting('group_id'),ident,'09:20','10:50'))
                c.execute('INSERT INTO lesson_rooms VALUES(?,?,?,?)',(owner,get_setting('group_id'),ident,'Новая аудитория'))
                c.execute('INSERT INTO hidden_lessons VALUES(?,?,?,?)',(owner,get_setting('group_id'),hidden,'now'))
                event={'date':DAY,'title':'Моя дополнительная пара','start':'12:00','end':'13:30','room':'777','teacher':'Преподаватель','type':'lesson'}
                c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',(('a' if owner==MEMBER else 'b')*32,owner,get_setting('group_id'),json.dumps(event)))
                c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',('f'*32,'member:someone-else',get_setting('group_id'),json.dumps(event|{'title':'secret-other-person'})))
            items=self.seen_records(viewer);self.assert_same(items,self.own_records(owner,group))
            self.assertEqual(len(items),2);self.assertEqual(items[0]['start'],'09:20');self.assertEqual(items[0]['room'],'Новая аудитория')
            self.assertEqual(items[1]['room'],'777')

    def test_pair_tracks_the_counterpart_current_study_group(self):
        new='fgu:99991';initialize_group(new)
        self.store(new,{'date':DAY,'lessons':[lesson('НОВАЯ ГРУППА',room='Новое место')]})
        for owner,viewer in ((MEMBER,self.admin_owner),(self.admin_owner,MEMBER)):
            with central_db() as c:set_profile(c,owner,new)
            payload=comparison.snapshot(viewer,DAY,at=self.now)
            self.assertEqual(payload['group']['id'],new);self.assertEqual(payload['days'][0]['lessons'][0]['title'],'Новая группа')
            self.assertEqual(comparison.target_for(viewer),new)
        self.assertIn(new,comparison.watched_groups())

    def test_shared_flags_and_both_reminder_streams_use_counterpart_choices(self):
        # The source contains a matching branch, but the admin selected another one.
        for group in (OWN,comparison.TARGET):
            raw={'date':DAY,'lessons':[lesson(teacher='Первый преподаватель'),lesson(room='Другой зал',teacher='Второй преподаватель')]}
            for i,item in enumerate(raw['lessons'],1):item['periods'][0].update(groups=str(i)+' п/г',typeStr='Практика')
            self.store(group,raw)
        subject=subject_key('ИСТОРИЯ РОССИИ')
        def choose(owner,group,marker):
            with group_context(group):
                raw=community.official_days();info=subgroups.describe(raw)[subject]
                value=next(option['id'] for option in info['options'].values() if option['group']==marker)
                subgroups.save_choices(owner,raw,{subject:value})
        choose(MEMBER,comparison.TARGET,'1 п/г');choose(self.admin_owner,OWN,'2 п/г')
        with group_context(comparison.TARGET):own=self.own_records(MEMBER,comparison.TARGET)[0]
        self.assertEqual(comparison.shared_marker(MEMBER,self.now)(own),'')
        self.assertEqual(comparison.snapshot(self.admin_owner,DAY,at=self.now)['today_common'],[])
        prefs=comparison.preferences(self.admin_owner)|{'notify_common':True}
        comparison.save_preferences(self.admin_owner,prefs)
        self.assertEqual(comparison.candidates(self.admin_owner,self.now),[])
        choose(self.admin_owner,OWN,'1 п/г')
        self.assertEqual(comparison.shared_marker(MEMBER,self.now)(own),'Общая пара с 107))')
        self.assertEqual(len(comparison.candidates(self.admin_owner,self.now)),1)
        from services.webpush import candidates
        push_prefs={'lessons':True,'deadlines':False,'lesson_minutes':15,'lesson_offsets':[15]}
        with group_context(comparison.TARGET):push=candidates(MEMBER,{},push_prefs,self.now)
        self.assertEqual(len(push),1);self.assertIn('Общая пара с 107))',push[0][1]['body'])

    def test_payload_never_exposes_counterpart_homework_files_identity_or_other_events(self):
        raw={'date':DAY,'lessons':[lesson()]};raw['lessons'][0]['periods'][0].update(homework='secret-homework',files=['secret-file'])
        self.store(comparison.TARGET,raw)
        with group_context(comparison.TARGET),community.db() as c:
            c.execute('INSERT OR REPLACE INTO content VALUES(?,?,?,?,?)',('homework','item','secret-homework','secret-person','now'))
            event={'date':DAY,'title':'secret-personal-event','start':'12:00','end':'13:30','type':'event','description':'secret-detail'}
            c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,1)',('c'*32,MEMBER,get_setting('group_id'),json.dumps(event)))
        payload=comparison.snapshot(self.admin_owner,DAY,at=self.now)
        text=json.dumps(payload)
        for value in ('secret-',MEMBER,'peer_owner','_diary_id'):self.assertNotIn(value,text)
        self.assertEqual(set(payload['days'][0]['lessons'][0]),{'date','number','title','start','end','room','teachers','type','common'})
        self.assertEqual(self.member.get('/api/group-comparison').status_code,403)

    def test_broken_or_inactive_binding_never_falls_back_to_all_subgroups(self):
        with self.assertRaises(ValueError):comparison.bind_pair('member:existing-member')
        with central_db() as c:c.execute("UPDATE members SET active=0 WHERE code=?",(MEMBER[7:],))
        self.assertIsNone(comparison.target_for(self.admin_owner))
        with self.assertRaises(ValueError):comparison.snapshot(self.admin_owner,DAY,at=self.now)
        with central_db() as c:
            c.execute('UPDATE members SET active=1 WHERE code=?',(MEMBER[7:],))
            c.execute('UPDATE group_comparison_access SET peer_owner=NULL WHERE owner=?',(MEMBER,))
        self.assertIsNone(comparison.target_for(self.admin_owner))
        with self.assertRaises(ValueError):comparison.snapshot(self.admin_owner,DAY,at=self.now)

    def test_account_deletion_cleans_both_sides_of_binding(self):
        import uuid
        other='member:pair-erasure-'+uuid.uuid4().hex
        with central_db() as c:
            c.execute('INSERT INTO members(code,name) VALUES(?,?)',(other[7:],'Удаляемый связанный участник'))
            set_profile(c,other,comparison.TARGET)
        comparison.grant_member(other,OWN);comparison.bind_pair(other)
        from services.privacy import process_one
        process_one(other,'account')
        with central_db() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM group_comparison_access WHERE owner=? OR peer_owner=?',(other,other)).fetchone())
