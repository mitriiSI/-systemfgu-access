import json
import time
from unittest.mock import patch

from test_admin_access import AccessFixture
from database import central_db
from services import admissions, subscriptions


class SubscriptionHistoryTests(AccessFixture):
    def setUp(self):
        super().setUp()
        with central_db() as c:
            for table in ('custom_lessons','hidden_lessons','content','revisions','proposals','subscription_overrides'):
                c.execute('DELETE FROM '+table)
            c.execute('UPDATE subscription_settings SET base_price=NULL')
            c.execute("INSERT OR REPLACE INTO university_groups VALUES('geo:test','geo','test','Тестовый геофак','Бакалавриат',1,'excel',NULL)")
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='custom_lesson_history'").fetchone():
                c.execute('DELETE FROM custom_lesson_history')
        self.lesson={'title':'Моя пара','type':'lesson','date':'2026-10-19','start':'10:00','end':'11:00',
                     'teachers':['Первый преподаватель','Второй преподаватель'],'recurrence':'weekly','visibility':'personal'}

    def other_faculty(self):
        admissions.assign_member(self.admin_owner,'existing-member','geo:test')

    def custom(self,**extra):
        result=self.post(self.member,'schedule/custom',self.lesson|extra)
        self.assertEqual(result.status_code,200)
        return result.get_json()['id']

    def history(self):
        response=self.member.get('/api/account/lesson-history')
        self.assertEqual(response.status_code,200)
        return response.get_json()['items']

    def events(self,day='2026-10-19'):
        return self.member.get('/api/schedule/events?start='+day+'&end='+day).get_json()

    def test_fgu_always_free_even_with_a_stored_override(self):
        subscriptions.set_base(self.admin_owner,19900)
        with central_db() as c:
            c.execute('INSERT INTO subscription_overrides VALUES(?,?,?,?,?,?)',('member:existing-member',9900,0,None,'now',self.admin_owner))
        value=self.member.get('/api/subscription').get_json()
        self.assertEqual((value['price'],value['mode']),(0,'fgu_free'))
        self.assertFalse(value['payments_enabled'])
        self.assertEqual(self.post(self.admin,'admin/subscriptions',{'member':'existing-member','price':9900}).status_code,400)

    def test_non_fgu_base_discount_free_expiry_and_reset(self):
        self.other_faculty()
        self.assertEqual(self.member.get('/api/subscription').get_json()['price'],None)
        self.assertEqual(self.post(self.admin,'admin/subscriptions',{'base_price':19900}).status_code,200)
        self.assertEqual(self.post(self.admin,'admin/subscriptions',{'member':'existing-member','price':9900}).status_code,200)
        self.assertEqual(self.member.get('/api/subscription').get_json()['price'],9900)
        stamp=time.time()
        self.assertEqual(self.post(self.admin,'admin/subscriptions',{'member':'existing-member','price':9900,'free':True,'free_until':stamp+100}).status_code,200)
        self.assertEqual(self.member.get('/api/subscription').get_json()['price'],0)
        with patch('services.subscriptions.time.time',return_value=stamp+101):
            self.assertEqual(subscriptions.status('member:existing-member')['price'],9900)
        self.post(self.admin,'admin/subscriptions',{'member':'existing-member','reset':True})
        value=self.member.get('/api/subscription').get_json()
        self.assertEqual(value['price'],19900)
        self.assertTrue(value['access_allowed'])
        self.assertFalse(value['payments_enabled'])
        admissions.assign_member(self.admin_owner,'existing-member',admissions.DEFAULT_GROUP)
        self.assertEqual(self.member.get('/api/subscription').get_json()['price'],0)

    def test_subscription_permissions_and_price_validation(self):
        self.other_faculty()
        self.assertEqual(self.post(self.member,'admin/subscriptions',{'base_price':19900}).status_code,403)
        self.assertEqual(self.admin.post('/api/admin/subscriptions',json={'base_price':19900}).status_code,403)
        for value in (-1,True,12.5,'100',100000001):
            self.assertEqual(self.post(self.admin,'admin/subscriptions',{'base_price':value}).status_code,400)
        self.post(self.admin,'admin/subscriptions',{'base_price':19900})
        self.assertEqual(self.post(self.admin,'admin/subscriptions',{'member':'existing-member','price':20000}).status_code,400)
        for value in ('nan','Infinity','1e99999999','-2','1.234'):
            with self.assertRaises(ValueError):subscriptions.rubles(value)

    def test_bot_can_manage_prices_and_free_access(self):
        self.other_faculty()
        with central_db() as c:c.execute("UPDATE members SET tg=860001 WHERE code='existing-member'")
        from bot.handlers import handle_command
        with patch('bot.handlers.tg_call',return_value={}):
            for text in ('/subscriptionprice 199','/discount 860001 99.50','/free 860001 30'):
                handle_command({'chat':{'type':'private','id':self.admin_id},'from':{'id':self.admin_id},'text':text})
        value=subscriptions.status('member:existing-member')
        self.assertEqual(value['base_price'],19900)
        self.assertEqual(value['price'],0)
        self.assertGreater(value['free_until'],time.time()+29*86400)

    def test_disabled_weekly_custom_lesson_restores_same_entry(self):
        ident=self.custom()
        self.assertEqual(len(self.events()),1)
        self.post(self.member,'schedule/custom',{'id':ident,'disable':True})
        self.assertEqual(self.events(),[])
        entry=next(row for row in self.history() if row['action']=='deleted')
        response=self.post(self.member,'account/lesson-history/restore',{'kind':'custom','id':entry['id']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.events()[0]['id'],ident)
        self.assertEqual(self.events('2026-10-26')[0]['teachers'],self.lesson['teachers'])
        self.assertEqual(self.history()[0]['action'],'restored')

    def test_old_disabled_custom_lesson_is_recoverable(self):
        with central_db() as c:
            c.execute('INSERT INTO custom_lessons VALUES(?,?,?,?,0)',('a'*32,'member:existing-member','1457',json.dumps(self.lesson)))
        entry=self.history()[0]
        self.assertEqual(entry['action'],'deleted')
        self.assertEqual(entry['created'],'')
        self.assertEqual(self.post(self.member,'account/lesson-history/restore',{'kind':'custom','id':entry['id']}).status_code,200)
        self.assertEqual(len(self.events()),1)

    def test_previous_version_can_be_restored_after_edit(self):
        ident=self.custom()
        self.custom(id=ident,title='Изменённая пара',teachers=['Новый преподаватель'])
        self.assertEqual(self.events()[0]['title'],'Изменённая пара')
        entry=next(row for row in self.history() if row['action']=='created')
        self.post(self.member,'account/lesson-history/restore',{'kind':'custom','id':entry['id']})
        self.assertEqual(self.events()[0]['title'],'Моя пара')
        self.assertEqual(self.events()[0]['teachers'],self.lesson['teachers'])

    def test_hidden_occurrence_is_restored_without_unhiding_other_dates(self):
        self.custom()
        for day in ('2026-10-26','2026-11-02'):
            occurrence=self.events(day)[0]['occurrence_id']
            self.assertEqual(self.post(self.member,'schedule/hide',{'id':occurrence,'date':day}).status_code,200)
        entry=next(row for row in self.history() if row['action']=='hidden' and row['hidden_date']=='2026-10-26')
        self.post(self.member,'account/lesson-history/restore',{'kind':'custom','id':entry['id']})
        self.assertEqual(len(self.events('2026-10-26')),1)
        self.assertEqual(self.events('2026-11-02'),[])

    def test_history_is_private_and_group_scoped(self):
        ident=self.custom()
        entry=self.history()[0]
        self.assertEqual(self.post(self.admin,'account/lesson-history/restore',{'kind':'custom','id':entry['id']}).status_code,404)
        self.assertEqual(self.admin.get('/api/schedule/custom/'+ident).status_code,404)
        self.assertEqual(self.admin.get('/api/account/lesson-history').get_json()['items'],[])
        admissions.assign_member(self.admin_owner,'existing-member','fgu:99991')
        self.assertEqual(self.history(),[])
        self.assertEqual(self.post(self.member,'account/lesson-history/restore',{'kind':'custom','id':entry['id']}).status_code,404)

    def test_shared_restore_keeps_moderation(self):
        data=self.lesson|{'recurrence':'once'}
        created=self.post(self.member,'schedule/events',data).get_json()['id']
        self.post(self.member,'schedule/events',{'id':created,'delete':True})
        entry=next(row for row in self.history() if row['kind']=='shared' and row['action']=='deleted')
        with central_db() as c:c.execute("INSERT OR REPLACE INTO settings VALUES('moderate_existing-member','1')")
        response=self.post(self.member,'account/lesson-history/restore',{'kind':'shared','id':entry['id']})
        self.assertEqual(response.get_json()['status'],'pending')
        self.assertEqual(self.events(),[])
        with central_db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM proposals WHERE kind='schedule_event'").fetchone()[0],1)

    def test_restore_requires_csrf(self):
        self.custom()
        entry=self.history()[0]
        self.assertEqual(self.member.post('/api/account/lesson-history/restore',json={'kind':'custom','id':entry['id']}).status_code,403)
