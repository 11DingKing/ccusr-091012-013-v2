from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import StockOutPerson


class StockOutPersonModelTest(TestCase):
    def test_create_and_render_person(self):
        person = StockOutPerson.objects.create(
            police_no="OUT001",
            name="王五",
            phone="13800138000",
        )
        self.assertEqual(person.police_no, "OUT001")
        self.assertIn("王五", str(person))
        self.assertTrue(person.is_active)


class StockOutPersonAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="personnel-user",
            password="testpass123",
            role="admin",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.url = "/api/stock-out-persons/"

    def test_create_list_update_and_delete_person(self):
        created = self.client.post(
            self.url,
            {
                "police_no": "OUT002",
                "name": "赵六",
                "phone": "13900139000",
                "id_card": "",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 200)
        person_id = created.json()["data"]["id"]

        listed = self.client.get(self.url)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["data"]["total"], 1)

        updated = self.client.put(
            f"{self.url}{person_id}/",
            {
                "police_no": "OUT002",
                "name": "赵六",
                "phone": "13700137000",
                "id_card": "",
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"]["phone"], "13700137000")

        deleted = self.client.delete(f"{self.url}{person_id}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(StockOutPerson.objects.filter(pk=person_id).exists())

    def test_reject_duplicate_identifiers(self):
        StockOutPerson.objects.create(
            police_no="OUT003",
            name="钱七",
            phone="13600136000",
        )
        response = self.client.post(
            self.url,
            {
                "police_no": "OUT003",
                "name": "孙八",
                "phone": "13500135000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
