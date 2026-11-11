import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audits import checklist
from audits.ac import ac_result
from audits.models import Audit, CheckType, Finding, Issue, IssueStatus, Room

MEDIA = tempfile.mkdtemp()
# A 1x1 GIF.
PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@override_settings(MEDIA_ROOT=MEDIA)
class AuditFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.user = User.objects.create_superuser("bryan", "", "pw")
        cls.room = Room.objects.get(number="101")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.user)
        self.audit = Audit.objects.create(room=self.room, cycle_year=2026, auditor=self.user)
        self.url = reverse("finding_update", args=[self.audit.pk])

    def key(self, name, check="condition"):
        for entries in checklist.build_all(self.audit).values():
            for entry in entries:
                if entry.label == name:
                    return next(r.key for r in entry.checks if r.check_type == check)
        raise AssertionError(f"{name} not in checklist")

    def test_login_is_required(self):
        self.client.logout()
        for url in ("/", "/issues/", "/dashboard/", f"/audits/{self.audit.pk}/entry/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response["Location"])

    def test_storage_cannot_be_audited(self):
        response = self.client.get("/")
        self.assertNotContains(response, "Storage")
        storage = Room.objects.get(is_storage=True)
        response = self.client.post(
            "/", {"room": storage.pk, "audit_type": "annual", "cycle_year": 2026}
        )
        self.assertEqual(response.status_code, 200)  # form error, no audit made
        self.assertFalse(Audit.objects.filter(room=storage).exists())

    def test_starting_an_audit_resumes_an_unfinished_one(self):
        response = self.client.post(
            "/", {"room": self.room.pk, "audit_type": "annual", "cycle_year": 2026}
        )
        self.assertRedirects(response, f"/audits/{self.audit.pk}/start/")
        self.assertEqual(Audit.objects.count(), 1)
        response = self.client.post(
            "/", {"room": self.room.pk, "audit_type": "annual", "cycle_year": 2027}
        )
        self.assertEqual(Audit.objects.count(), 2)

    def test_every_zone_lists_every_item_with_nothing_preselected(self):
        counts = checklist.zone_counts(self.audit)
        # entry: 3 + walls/floor/windows/trim/signage; no function checks
        self.assertEqual(counts["entry"], (8, 8))
        for zone in ("entry", "bedroom", "bathroom"):
            response = self.client.get(f"/audits/{self.audit.pk}/{zone}/")
            self.assertEqual(response.status_code, 200)
            total = counts[zone][0]
            self.assertContains(response, "Unanswered</span>", count=total)
            self.assertNotContains(response, 'selected"')
        self.assertEqual(Finding.objects.count(), 0)

    def test_check_types_per_item(self):
        rows = {
            (entry.label, row.check_type)
            for entries in checklist.build_all(self.audit).values()
            for entry in entries
            for row in entry.checks
        }
        self.assertIn(("Bed frame", "noise"), rows)
        self.assertIn(("Mattress", "noise"), rows)
        self.assertIn(("Mattress", "pest"), rows)
        self.assertNotIn(("Bed frame", "pest"), rows)
        self.assertIn(("TV", "function"), rows)
        self.assertIn(("A/C", "function"), rows)
        self.assertNotIn(("A/C filter", "function"), rows)
        self.assertNotIn(("Towel rack", "function"), rows)
        self.assertNotIn(("Chair #1", "function"), rows)

    def test_tapping_a_result_saves_a_finding(self):
        response = self.client.post(self.url, {"key": self.key("TV"), "result": "ok"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "good selected")
        self.assertNotContains(response, "Pick an action")
        finding = Finding.objects.get()
        self.assertEqual((finding.result, finding.fixture.name), ("ok", "TV"))
        self.assertEqual(Issue.objects.count(), 0)

    def test_problem_result_asks_for_a_bucket_and_then_opens_an_issue(self):
        key = self.key("Chair #2")
        response = self.client.post(self.url, {"key": key, "result": "damaged"})
        self.assertContains(response, "Pick an action")
        self.assertEqual(Issue.objects.count(), 0)
        response = self.client.post(self.url, {"key": key, "action_bucket": "capex"})
        self.assertContains(response, "bucket selected")
        issue = Issue.objects.get()
        self.assertEqual((issue.bucket, issue.title), ("capex", "Chair #2 (Bedroom): Damaged"))
        # Editing the saved finding back to OK closes the issue.
        self.client.post(self.url, {"key": key, "result": "ok"})
        issue.refresh_from_db()
        self.assertEqual(issue.status, IssueStatus.DONE)
        self.assertEqual(Finding.objects.get().action_bucket, "")

    def test_other_opens_a_free_text_field(self):
        key = self.key("Mirror")
        response = self.client.post(self.url, {"key": key, "result": "other"})
        self.assertContains(response, 'name="result_other"')
        self.client.post(self.url, {"key": key, "result_other": "Desilvering at edge"})
        self.assertEqual(Finding.objects.get().result_other, "Desilvering at edge")
        response = self.client.post(self.url, {"key": key, "result": "ok"})
        self.assertNotContains(response, 'name="result_other"')
        self.assertEqual(Finding.objects.get().result_other, "")

    def test_squeak_and_bedbug_checks_are_pass_or_fail(self):
        response = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(response, "Squeak test", count=2)
        self.assertContains(response, "Bedbug check", count=1)
        self.client.post(self.url, {"key": self.key("Mattress", "pest"), "result": "fail"})
        self.assertEqual(Finding.objects.get().check_type, CheckType.PEST)
        response = self.client.post(
            self.url, {"key": self.key("Mattress", "pest"), "result": "worn"}
        )
        self.assertEqual(response.status_code, 400)

    def test_clearing_a_result_marks_it_unanswered_again(self):
        key = self.key("TV")
        self.client.post(self.url, {"key": key, "result": "damaged"})
        self.client.post(self.url, {"key": key, "action_bucket": "fix_now"})
        response = self.client.post(self.url, {"key": key, "result": ""})
        self.assertContains(response, "Unanswered")
        self.assertEqual(Issue.objects.get().status, IssueStatus.DONE)

    def test_note_and_photo(self):
        key = self.key("Toilet")
        self.client.post(self.url, {"key": key, "result": "damaged"})
        self.client.post(self.url, {"key": key, "notes": "Cracked tank lid"})
        photo = SimpleUploadedFile("lid.gif", PIXEL, content_type="image/gif")
        response = self.client.post(self.url, {"key": key, "photo": photo})
        self.assertContains(response, "Remove photo")
        finding = Finding.objects.get()
        self.assertEqual(finding.notes, "Cracked tank lid")
        self.assertTrue(finding.photo.name.startswith("findings/"))
        self.client.post(self.url, {"key": key, "remove_photo": "1"})
        self.assertFalse(Finding.objects.get().photo)

    def test_unknown_key_or_other_rooms_item_is_rejected(self):
        other = Room.objects.get(number="102").fixtures.first()
        for key in ("nope", f"fixture-{other.pk}-condition"):
            self.assertEqual(self.client.post(self.url, {"key": key, "result": "ok"}).status_code, 404)

    def test_missing_expected_item_appears_and_can_be_marked_missing(self):
        self.room.building_elements.filter(element="threshold").delete()
        response = self.client.get(f"/audits/{self.audit.pk}/entry/")
        self.assertContains(response, "Expected, not in inventory")
        key = self.key("Threshold", "presence")
        self.client.post(self.url, {"key": key, "result": "missing"})
        self.client.post(self.url, {"key": key, "action_bucket": "work_order"})
        self.assertEqual(Issue.objects.get().title, "Threshold (Entry): Missing")

    def test_decor_is_added_during_the_audit(self):
        self.assertFalse(self.room.furnishings.filter(category="decor").exists())
        self.client.post(f"/audits/{self.audit.pk}/decor/", {"description": "Beach print"})
        self.assertEqual(self.room.furnishings.get(category="decor").name, "Beach print")
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), "Beach print")

    def test_start_step_saves_temperature_square_footage_and_first_reading(self):
        response = self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {
                "ambient_temperature_f": "71.5",
                "square_footage": "240",
                "ac_start_value": "78",
                "ac_start_time": "2026-11-10T14:00",
                "action": "continue",
            },
        )
        self.assertRedirects(response, f"/audits/{self.audit.pk}/entry/")
        self.audit.refresh_from_db()
        self.room.refresh_from_db()
        self.assertEqual(self.audit.ambient_temperature_f, Decimal("71.5"))
        self.assertEqual(self.room.square_footage, 240)
        result = ac_result(self.audit)
        self.assertEqual(result.start_value, Decimal("78.0"))
        local = timezone.localtime(result.start_at)
        self.assertEqual((local.hour, local.minute, str(local.tzinfo)), (14, 0, "America/Los_Angeles"))

    def test_square_footage_is_only_asked_on_the_first_audit(self):
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/start/"), "square footage")
        self.room.square_footage = 240
        self.room.save()
        later = Audit.objects.create(room=self.room, cycle_year=2027)
        self.assertNotContains(self.client.get(f"/audits/{later.pk}/start/"), "square footage")

    def test_wrapup_calculates_the_ac_result_and_finishes_the_audit(self):
        self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {"ac_start_value": "78", "ac_start_time": "2026-11-10T14:00", "action": "save"},
        )
        response = self.client.post(
            f"/audits/{self.audit.pk}/wrapup/",
            {
                "ac_end_value": "57.5",
                "ac_end_time": "2026-11-10T14:08",
                "overall_rating": "3",
                "overall_notes": "Fine overall",
                "action": "save",
            },
            follow=True,
        )
        self.assertContains(response, "8.0 min")
        self.assertContains(response, "20.5°F")
        self.assertContains(response, "tag pass")
        self.audit.refresh_from_db()
        self.assertEqual(self.audit.overall_rating, 3)
        self.assertIsNone(self.audit.end_time)

        self.client.post(
            f"/audits/{self.audit.pk}/wrapup/",
            {"ac_end_value": "57.5", "ac_end_time": "2026-11-10T14:08", "action": "finish"},
        )
        self.audit.refresh_from_db()
        self.assertIsNotNone(self.audit.end_time)

    def test_reading_time_defaults_to_now(self):
        before = timezone.now() - timedelta(seconds=1)
        self.client.post(
            f"/audits/{self.audit.pk}/start/", {"ac_start_value": "78", "action": "save"}
        )
        self.assertGreaterEqual(ac_result(self.audit).start_at, before)

    def test_audit_can_be_saved_with_unanswered_items_and_resumed(self):
        self.client.post(self.url, {"key": self.key("TV"), "result": "ok"})
        self.client.post(f"/audits/{self.audit.pk}/wrapup/", {"action": "finish"})
        response = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(response, "good selected", count=1)
        total, unanswered = checklist.zone_counts(self.audit)["bedroom"]
        self.assertEqual(unanswered, total - 1)
        self.assertContains(response, f"{unanswered} unanswered")
