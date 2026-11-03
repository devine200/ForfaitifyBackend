from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()

ADULT = {
    "email": "ada@example.com",
    "password": "Sup3r-secret-pass",
    "full_name": "Ada Merchant",
    "country": "Nigeria",
    "phone": "+2348000000000",
    "date_of_birth": "1990-05-01",
    "role": "merchant",
}


class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_underage_rejected(self):
        payload = {**ADULT, "date_of_birth": "2015-01-01"}
        response = self.client.post("/api/v1/auth/register", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "underage")
        self.assertFalse(User.objects.filter(email=ADULT["email"]).exists())

    @patch("accounts.views.issue_otp")
    def test_same_email_can_add_the_other_role(self, _otp):
        created = self.client.post("/api/v1/auth/register", ADULT, format="json")
        self.assertEqual(created.status_code, 201)
        user = User.objects.get(email=ADULT["email"])
        user.email_verified = True
        user.is_active = True
        user.save(update_fields=["email_verified", "is_active"])

        added = self.client.post(
            "/api/v1/auth/register",
            {**ADULT, "role": "investor"},
            format="json",
        )
        self.assertEqual(added.status_code, 201)
        self.assertEqual(added.data["code"], "otp_required")
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_merchant)
        self.assertFalse(user.has_investor)

        self.client.force_authenticate(user=user)
        agreed = self.client.post(
            "/api/v1/auth/investor-agreement",
            {"accepted": True},
            format="json",
        )
        self.assertEqual(agreed.status_code, 200, agreed.data)
        self.assertIsNotNone(agreed.data["investor_profile"]["agreement_accepted_at"])
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_investor)

    @patch("accounts.views.issue_otp")
    def test_verified_underage_record_accepts_a_new_adult_birthday(self, _otp):
        created = self.client.post("/api/v1/auth/register", ADULT, format="json")
        self.assertEqual(created.status_code, 201)
        user = User.objects.get(email=ADULT["email"])
        user.email_verified = True
        user.is_active = True
        user.date_of_birth = "2026-10-29"
        user.save(update_fields=["email_verified", "is_active", "date_of_birth"])

        added = self.client.post(
            "/api/v1/auth/register",
            {**ADULT, "role": "investor", "date_of_birth": "1992-03-04"},
            format="json",
        )
        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(added.data["code"], "otp_required")
        user.refresh_from_db()
        self.assertEqual(str(user.date_of_birth), "1992-03-04")
        self.assertFalse(user.has_investor)
