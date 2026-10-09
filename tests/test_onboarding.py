"""The walkthrough marker belongs to the authenticated account, across devices."""
from test_admin_access import AccessFixture
from database import central_db
from services import admissions


class OnboardingTests(AccessFixture):
    def setUp(self):
        super().setUp()
        with central_db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'onboarding_v1_%'")

    def test_completion_survives_a_new_browser_and_group_assignment(self):
        self.assertFalse(self.member.get('/api/me').get_json()['onboarding_seen'])
        self.assertEqual(self.post(self.member, 'account/onboarding', {}).status_code, 200)
        fresh = self.client(code='existing-member')
        self.assertTrue(fresh.get('/api/me').get_json()['onboarding_seen'])
        admissions.assign_member(self.admin_owner, 'existing-member', 'fgu:99991')
        self.assertTrue(fresh.get('/api/me').get_json()['onboarding_seen'])

    def test_completion_cannot_mark_another_account(self):
        self.post(self.member, 'account/onboarding', {'owner': self.admin_owner})
        self.assertTrue(self.member.get('/api/me').get_json()['onboarding_seen'])
        self.assertFalse(self.admin.get('/api/me').get_json()['onboarding_seen'])
        with central_db() as c:
            c.execute("INSERT INTO members(code,name) VALUES('onboarding-other','Другой участник')")
            admissions.set_profile(c, 'member:onboarding-other', admissions.DEFAULT_GROUP)
        self.assertFalse(self.client(code='onboarding-other').get('/api/me').get_json()['onboarding_seen'])

    def test_completion_requires_authentication_and_csrf(self):
        self.assertEqual(self.app.test_client().post('/api/account/onboarding', json={}).status_code, 401)
        self.assertEqual(self.member.post('/api/account/onboarding', json={}).status_code, 403)
        self.assertFalse(self.member.get('/api/me').get_json()['onboarding_seen'])
        self.assertEqual(self.post(self.admin, 'account/onboarding', {}).status_code, 200)
        self.assertTrue(self.admin.get('/api/me').get_json()['onboarding_seen'])
