"""Malformed input, disk-growth quotas and the bodyless upload admission check."""
import json
import secrets
import io

from test_admin_access import AccessFixture
from database import central_db, group_context, initialize_group
from services.admissions import set_profile
from services import community


class ResilienceTests(AccessFixture):
    def setUp(self):
        super().setUp()
        initialize_group('fgp:101')
        with central_db() as c:
            set_profile(c,'member:existing-member','fgp:101')
            set_profile(c,self.admin_owner,'fgp:101')
        with group_context('fgp:101'),community.db() as c:
            c.execute("DELETE FROM personal WHERE owner='member:existing-member'")

    def test_untrusted_types_unicode_and_integers_return_400_without_crashing(self):
        cases=[('study-group',{'faculty':'ffl','group':[1]}),
               ('schedule/hide',{'date':'2026-10-08','id':[]}),
               ('schedule/hide',{'date':'2026-10-08','id':{}}),
               ('schedule/custom',{'disable':True,'id':[]}),
               ('schedule/custom',{'disable':True,'id':2**100}),
               ('schedule/import/commit',{'token':[]}),
               ('schedule/import/commit',{'token':2**100}),
               ('account/name',{'name':'\ud800x'}),
               ('personal',{'kind':'note','item':'x','body':'\udfff'}),
               ('personal',{'kind':'note','item':'x','body':float('inf')})]
        for path,body in cases:
            with self.subTest(path=path):self.assertEqual(self.post(self.member,path,body).status_code,400)
        for path,body in [('teacher-permissions',{'allowed':True,'code':[]}),('material-sets/merge',{'source':2**100,'target':1})]:
            self.assertEqual(self.post(self.admin,path,body).status_code,400)

    def test_deep_json_and_non_finite_numbers_rejected_before_business_logic(self):
        for raw in ['{"x":NaN}','{"x":1e999}','{"x":'+'['*1100+'0'+']'*1100+'}', '{"x":'+'['*40+'0'+']'*40+'}']:
            response=self.app.test_client().post('/api/register',data=raw,content_type='application/json')
            self.assertEqual(response.status_code,400)

    def test_large_json_cannot_use_multipart_upload_allowance(self):
        for path in ('files','schedule/import/preview'):
            response=self.member.post('/api/'+path,data='{"body":"'+'x'*70000+'"}',content_type='application/json',headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(response.status_code,413)

    def test_multipart_options_use_the_same_strict_json_limits(self):
        for raw in ['{"x":'+'['*1100+'0'+']'*1100+'}', '{"x":"\\ud800"}']:
            response=self.member.post('/api/schedule/import/preview',data={'options':raw,'file':(io.BytesIO(b'fake PDF'),'test.pdf')},headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(response.status_code,400)

    def test_real_unicode_and_supported_integer_boundary_still_work(self):
        response=self.post(self.member,'personal',{'kind':'note','item':'resilience-unicode','body':'中文 😀 Заметка','extra':2**63-1})
        self.assertEqual(response.status_code,200)
        self.assertIn('中文 😀 Заметка',[row['body'] for row in self.member.get('/api/personal').get_json()])

    def test_new_groups_have_atomic_daily_quota_but_existing_groups_are_selectable(self):
        prefix='resilience-'+secrets.token_hex(5)
        body={'faculty':'ffl','level':'Бакалавриат','course':1}
        ids=[]
        for n in range(5):
            response=self.post(self.member,'study-group',body|{'group_name':prefix+str(n)})
            self.assertEqual(response.status_code,200);ids.append(response.get_json()['group']['id'])
        self.assertEqual(self.post(self.member,'study-group',body|{'group_name':prefix+'six'}).status_code,429)
        with central_db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM university_groups WHERE name LIKE ?',(prefix+'%',)).fetchone()[0],5)
        self.assertEqual(self.post(self.member,'study-group',{'faculty':'ffl','group':ids[0]}).status_code,200)

    def test_personal_note_quota_allows_edits_and_deletions(self):
        with group_context('fgp:101'),community.db() as c:
            c.execute("DELETE FROM personal WHERE owner='member:existing-member'")
            c.executemany('INSERT INTO personal VALUES(?,?,?,?,?)',[('member:existing-member','note','quota-'+str(n),'existing','now') for n in range(1000)])
        self.assertEqual(self.post(self.member,'personal',{'kind':'note','item':'another','body':'new'}).status_code,400)
        self.assertEqual(self.post(self.member,'personal',{'kind':'note','item':'quota-0','body':'updated'}).status_code,200)
        self.assertEqual(self.post(self.member,'personal',{'kind':'note','item':'quota-0','delete':True}).status_code,200)
        self.assertEqual(self.post(self.member,'personal',{'kind':'note','item':'another','body':'new'}).status_code,200)

    def test_administrator_can_edit_shared_custom_class_while_members_cannot(self):
        body={'title':'Shared class','date':'2026-10-08','start':'09:00','end':'10:00','type':'lesson','recurrence':'once','visibility':'group'}
        created=self.post(self.admin,'schedule/custom',body);self.assertEqual(created.status_code,200)
        ident=created.get_json()['id'];body['id']=ident;body['title']='Edited class'
        self.assertEqual(self.post(self.admin,'schedule/custom',body).status_code,200)
        body['visibility']='personal'
        self.assertEqual(self.post(self.member,'schedule/custom',body).status_code,403)

    def test_upload_admission_requires_session_csrf_and_same_site(self):
        self.assertEqual(self.app.test_client().get('/api/upload-check').status_code,401)
        self.assertEqual(self.member.get('/api/upload-check').status_code,403)
        self.assertEqual(self.member.get('/api/upload-check',headers={'X-CSRF-Token':'test-csrf'}).status_code,204)
        self.assertEqual(self.member.get('/api/upload-check',headers={'X-CSRF-Token':'test-csrf','Origin':'https://evil.test'}).status_code,403)
