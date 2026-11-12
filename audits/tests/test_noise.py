from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from audits import checklist
from audits.ac import ac_result
from audits.models import (
    NOISE_INSIDE_LABEL,
    NOISE_OUTSIDE_LABEL,
    Audit,
    CheckType,
    Finding,
    Issue,
    Room,
)
from audits.noise import NoiseResult, noise_result, set_noise


class NoiseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.user = User.objects.create_superuser("bryan", "", "pw")
        cls.room = Room.objects.get(number="101")

    def setUp(self):
        self.client.force_login(self.user)
        self.audit = Audit.objects.create(room=self.room, cycle_year=2026)

    def test_reduction_is_calculated_only_when_both_exist(self):
        self.assertEqual(NoiseResult(Decimal("72.5"), Decimal("41.0")).reduction, Decimal("31.5"))
        self.assertIsNone(NoiseResult(outside=Decimal("72.5")).reduction)
        self.assertFalse(NoiseResult().recorded)

    def test_readings_are_room_level_measurement_findings_in_db(self):
        set_noise(self.audit, "outside", Decimal("72.5"))
        set_noise(self.audit, "inside", Decimal("41.0"))
        findings = {f.measurement_label: f for f in self.audit.findings.all()}
        self.assertEqual(set(findings), {NOISE_OUTSIDE_LABEL, NOISE_INSIDE_LABEL})
        for finding in findings.values():
            self.assertEqual(finding.check_type, CheckType.MEASUREMENT)
            self.assertEqual(finding.unit, "dB")
            self.assertIsNotNone(finding.measured_at)
            self.assertIsNone(finding.target)
            self.assertEqual(finding.target_label, finding.measurement_label)
        self.assertEqual(Issue.objects.count(), 0)
        self.assertEqual(noise_result(self.audit).reduction, Decimal("31.5"))

    def test_saving_again_updates_and_blank_removes(self):
        first = set_noise(self.audit, "inside", Decimal("41.0"))
        same = set_noise(self.audit, "inside", Decimal("41.0"))
        self.assertEqual(first.measured_at, same.measured_at)  # unchanged value keeps its time
        set_noise(self.audit, "inside", Decimal("45.0"))
        self.assertEqual(Finding.objects.count(), 1)
        self.assertEqual(noise_result(self.audit).inside, Decimal("45.0"))
        set_noise(self.audit, "inside", None)
        self.assertEqual(Finding.objects.count(), 0)

    def test_outside_reading_is_entered_on_the_start_step(self):
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(page, "Peak noise outside (dB)")
        self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {"noise_outside_db": "72.5", "ac_start_value": "78", "action": "save"},
        )
        self.assertEqual(noise_result(self.audit).outside, Decimal("72.5"))
        self.assertEqual(ac_result(self.audit).start_value, Decimal("78.0"))  # A/C unaffected
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(page, 'value="72.5"')
        # Clearing the field removes the reading.
        self.client.post(f"/audits/{self.audit.pk}/start/", {"noise_outside_db": "", "action": "save"})
        self.assertIsNone(noise_result(self.audit).outside)

    def test_inside_reading_is_entered_on_the_bedroom_step_only(self):
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), "Peak noise inside")
        self.assertNotContains(self.client.get(f"/audits/{self.audit.pk}/bathroom/"), "Peak noise inside")
        url = f"/audits/{self.audit.pk}/noise-inside/"
        self.assertEqual(self.client.post(url, {"value": "41"}).status_code, 204)
        self.assertEqual(noise_result(self.audit).inside, Decimal("41.0"))
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), 'value="41.0"')
        self.assertEqual(self.client.post(url, {"value": "loud"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"value": "250"}).status_code, 400)
        self.assertEqual(noise_result(self.audit).inside, Decimal("41.0"))
        self.assertEqual(self.client.post(url, {"value": ""}).status_code, 204)
        self.assertIsNone(noise_result(self.audit).inside)

    def test_noise_is_optional_and_shown_on_wrap_up(self):
        before = checklist.zone_counts(self.audit)
        self.assertNotContains(self.client.get(f"/audits/{self.audit.pk}/wrapup/"), "Peak noise")
        set_noise(self.audit, "outside", Decimal("72.5"))
        self.assertEqual(checklist.zone_counts(self.audit), before)
        page = self.client.get(f"/audits/{self.audit.pk}/wrapup/")
        self.assertContains(page, "outside 72.5 dB")
        self.assertContains(page, "inside not logged")
        set_noise(self.audit, "inside", Decimal("41.0"))
        page = self.client.get(f"/audits/{self.audit.pk}/wrapup/")
        self.assertContains(page, "inside 41.0 dB")
        self.assertContains(page, "difference 31.5 dB")
