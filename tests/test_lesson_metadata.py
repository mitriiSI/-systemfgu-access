"""Private FGU corrections and presentation must retain saved lesson identities."""
import copy
import json
from unittest.mock import patch
import test_subgroups as fixtures
from database import group_context,get_setting
from services import community,lesson_times


class LessonMetadataTests(fixtures.GroupFixture):
    def setUp(self):
        super().setUp()
        with group_context(fixtures.GROUP),community.db() as c:
            lesson_times.initialize(c);lesson_times.initialize_rooms(c)
            c.execute('DELETE FROM lesson_times');c.execute('DELETE FROM lesson_rooms')

    def first(self,client=None):
        result=(client or self.member).get('/api/schedule').get_json()
        return next(day for day in result['days'] if day['date']==fixtures.DAY)['lessons'][0]['periods'][0]

    def test_fgu_time_and_room_are_private_and_restore_independently(self):
        initial=self.first();ident=initial['_diary_id'];body={'id':ident,'date':fixtures.DAY}
        self.assertEqual(self.post(self.member,'schedule/time',body|{'start':'09:20','end':'10:50'}).status_code,200)
        self.assertEqual(self.post(self.member,'schedule/room',body|{'room':'Первый учебный корпус, 301'}).status_code,200)
        mine=self.first();other=self.first(self.other)
        self.assertEqual((mine['timeStart'],mine['classroom']),('09:20','Первый учебный корпус, 301'))
        self.assertEqual((other['timeStart'],other['classroom']),('09:00','101'))
        self.assertEqual(mine['_diary_id'],ident)
        self.assertEqual(self.post(self.member,'schedule/room',body|{'restore':True}).status_code,200)
        self.assertEqual((self.first()['timeStart'],self.first()['classroom']),('09:20','101'))
        self.assertEqual(self.post(self.member,'schedule/time',body|{'restore':True}).status_code,200)
        self.assertEqual(self.first()['timeStart'],'09:00')

    def test_room_validation_and_other_persons_occurrence(self):
        body={'id':self.first()['_diary_id'],'date':fixtures.DAY}
        for value in (None,True,'x'*121,'301\n302'):
            self.assertEqual(self.post(self.member,'schedule/room',body|{'room':value}).status_code,400)
        self.assertEqual(self.post(self.member,'schedule/room',body|{'id':'unknown','room':'301'}).status_code,404)
        ident='7'*32
        with group_context(fixtures.GROUP),community.db() as c:
            event={'title':'Личная пара','date':fixtures.DAY,'start':'16:00','end':'17:00','type':'lesson','recurrence':'once'}
            c.execute('INSERT OR REPLACE INTO custom_lessons VALUES(?,?,?,?,1)',(ident,'member:second-member',get_setting('group_id'),json.dumps(event)))
        private={'id':'event:'+ident+':'+fixtures.DAY,'date':fixtures.DAY,'room':'301'}
        self.assertEqual(self.post(self.member,'schedule/room',private).status_code,404)
        self.assertEqual(self.post(self.other,'schedule/room',private).status_code,200)

    def test_room_export_contains_only_own_corrections(self):
        body={'id':self.first()['_diary_id'],'date':fixtures.DAY}
        self.assertEqual(self.post(self.member,'schedule/room',body|{'room':'Личная 301'}).status_code,200)
        self.assertEqual(self.post(self.other,'schedule/room',body|{'room':'Чужая 302'}).status_code,200)
        export=self.member.get('/api/account/export').get_json()
        rooms=[row['room'] for group in export['groups'] for row in group.get('lesson_rooms',[])]
        self.assertEqual(rooms,['Личная 301'])

    def test_cached_geography_labels_preserve_identity_and_original_records(self):
        raw=copy.deepcopy(self.raw);period=raw['lessons'][0]['periods'][0]
        period['disciplineFullName']='ФИЗИЧЕСКАЯ КУЛЬТУРА Трехзальный корпус 9 октября'
        before=copy.deepcopy(raw);self.store(raw)
        with group_context(fixtures.GROUP),patch('services.community.current_faculty',return_value='geo'):
            displayed=community.filtered_days(fixtures.OWNER,[raw])[0]['lessons'][0]['periods'][0]
            expected_id=community.lesson_id(fixtures.DAY,raw['lessons'][0],period)
        self.assertEqual(displayed['_diary_title'],'Физическая культура')
        self.assertEqual(displayed['classroom'],'101, Трехзальный корпус')
        self.assertEqual(displayed['_diary_id'],expected_id)
        self.assertEqual(displayed['disciplineFullName'],period['disciplineFullName'])
        self.assertEqual(raw,before)
