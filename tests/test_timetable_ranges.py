"""Future source responses include empty days outside the requested interval."""
import json
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch

from test_subgroups import GroupFixture,GROUP
from database import group_context,get_setting
from services import community,timetable


class TimetableRangeTests(GroupFixture):
    def test_extended_source_range_keeps_only_requested_days(self):
        def response(url,json,timeout):
            first=date.fromisoformat(json['dateStart'])
            rows=[{'date':(first-timedelta(days=14)).isoformat(),'lessons':[]},
                  dict(self.raw,date=first.isoformat()),
                  {'date':(date.fromisoformat(json['dateEnd'])+timedelta(days=1)).isoformat(),'lessons':[]}]
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:rows)
        with patch('services.timetable.requests.post',side_effect=response) as fetch:
            self.assertTrue(timetable.sync_schedule(GROUP))
        expected={call.kwargs['json']['dateStart'] for call in fetch.call_args_list}|{self.raw['date']}
        with group_context(GROUP),community.db() as c:
            actual={row[0] for row in c.execute('SELECT day FROM schedules')}
            self.assertTrue(actual<=expected,(actual,expected))
            self.assertEqual(get_setting('sync_error_1454'),'')

    def test_invalid_source_does_not_delete_saved_classes(self):
        response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:[{'date':'bad-date','lessons':[]}])
        with patch('services.timetable.requests.post',return_value=response):
            self.assertFalse(timetable.sync_schedule(GROUP))
        self.assertEqual(len(self.visible()),3)
        with group_context(GROUP):
            self.assertNotIn('ValueError',get_setting('sync_error_1454'))

    def test_unrelated_response_cannot_clear_a_week(self):
        with self.assertRaises(ValueError):
            timetable.requested_days([{'date':'2000-01-01','lessons':[]}],date(2026,10,5),date(2026,10,11))

    def test_invalid_row_in_extended_response_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            timetable.requested_days([{'date':'2026-10-05','lessons':[]},{'date':'2026-09-01','lessons':'invalid'}],date(2026,10,5),date(2026,10,11))
