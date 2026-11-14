from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APITestCase

User = get_user_model()


class ScopeTests(APITestCase):
    """Le périmètre servi par l'API est celui de scopeOf dans index.html."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))

    def as_person(self, code):
        user = User.objects.get(person_code=code)
        self.client.force_authenticate(user)
        return user

    def codes(self):
        return sorted(p["code"] for p in self.client.get("/api/projects").json())

    def test_projects_match_page_scope(self):
        expected = {
            "nh": ["NDL-GED", "NDL-MIG", "NDL-UNI", "ORP-PAT", "VAU-DIG"],  # direction : tout
            "sm": ["NDL-GED", "NDL-MIG", "NDL-UNI"],                      # cheffe de projet
            "ib": ["NDL-GED", "NDL-MIG", "NDL-UNI", "ORP-PAT"],           # consultante
            "nb": ["ORP-PAT"],                                            # manager Santé
            "lf": ["NDL-GED", "NDL-MIG", "NDL-UNI"],                      # client Nordline
        }
        for code, codes in expected.items():
            self.as_person(code)
            self.assertEqual(self.codes(), codes, code)

    def test_out_of_scope_project_is_not_found(self):
        self.as_person("nb")
        self.assertEqual(self.client.get("/api/projects/p1/actions").status_code, 404)

    def test_client_sees_only_own_and_client_tasks(self):
        user = self.as_person("lf")
        actions = self.client.get("/api/projects/p1/actions").json()
        self.assertTrue(actions)
        self.assertTrue(all(a["type"] == "Client" or a["owner"] == user.display_name for a in actions))

    def test_commercial_without_action_read_sees_no_team_tasks(self):
        self.as_person("cd")  # matrice : Commercial n'a pas action.read
        self.assertEqual(self.client.get("/api/projects/p1/actions").json(), [])
