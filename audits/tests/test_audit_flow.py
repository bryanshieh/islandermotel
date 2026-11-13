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
SMELL = "room-0"


@override_settings(MEDIA_ROOT=MEDIA)
class FlowTestCase(TestCase):
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
        self.url = reverse("item_update", args=[self.audit.pk])

    def entry(self, label):
        for entries in checklist.build_all(self.audit).values():
            for entry in entries:
                if entry.label == label:
                    return entry
        raise AssertionError(f"{label} not in checklist")

    def tap(self, label, result, check="condition"):
        """Tap a result button on one of an item's checks."""
        entry = self.entry(label)
        key = next(r.key for r in entry.checks if r.check_type == check)
        return self.client.post(self.url, {"item": entry.key, "key": key, "result": result})

    def act(self, label, bucket):
        return self.client.post(self.url, {"item": self.entry(label).key, "action_bucket": bucket})

    def post_item(self, label, **data):
        return self.client.post(self.url, {"item": self.entry(label).key, **data})


class AuditStartTests(FlowTestCase):
    def test_login_is_required(self):
        self.client.logout()
        for url in ("/", "/issues/", "/dashboard/", f"/audits/{self.audit.pk}/bedroom/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response["Location"])

    def test_storage_cannot_be_audited(self):
        self.assertNotContains(self.client.get("/"), "Storage")
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
        self.client.post("/", {"room": self.room.pk, "audit_type": "annual", "cycle_year": 2027})
        self.assertEqual(Audit.objects.count(), 2)

    def test_steps_are_start_bedroom_bathroom_other_wrapup(self):
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        for step in ("start", "bedroom", "bathroom", "other", "wrapup"):
            self.assertContains(page, f"/audits/{self.audit.pk}/{step}/")
        self.assertEqual(self.client.get(f"/audits/{self.audit.pk}/entry/").status_code, 404)

    def test_start_saves_outside_temperature_and_ac_on_time(self):
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(page, "Outside temperature")
        self.assertContains(page, "A/C on")
        self.assertNotContains(page, "first reading")
        response = self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {"ambient_temperature_f": "88.5", "ac_on_time": "2026-11-10T14:00", "action": "continue"},
        )
        self.assertRedirects(response, f"/audits/{self.audit.pk}/bedroom/")
        self.audit.refresh_from_db()
        self.assertEqual(self.audit.ambient_temperature_f, Decimal("88.5"))
        local = timezone.localtime(self.audit.ac_on_at)
        self.assertEqual((local.hour, local.minute, str(local.tzinfo)), (14, 0, "America/Los_Angeles"))
        self.assertEqual(Finding.objects.count(), 0)  # no A/C reading at the start any more

    def test_ac_on_now_saves_the_current_time_straight_away(self):
        before = timezone.now() - timedelta(seconds=1)
        response = self.client.post(f"/audits/{self.audit.pk}/ac-on/")
        self.assertContains(response, "A/C on since")
        self.audit.refresh_from_db()
        self.assertGreaterEqual(self.audit.ac_on_at, before)
        # The Start form then carries that time, so pressing Save keeps it.
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        stamp = timezone.localtime(self.audit.ac_on_at).strftime("%Y-%m-%dT%H:%M")
        self.assertContains(page, f'value="{stamp}"')
        self.client.post(
            f"/audits/{self.audit.pk}/start/", {"ac_on_time": stamp, "action": "save"}
        )
        self.audit.refresh_from_db()
        self.assertEqual(timezone.localtime(self.audit.ac_on_at).strftime("%Y-%m-%dT%H:%M"), stamp)

    def test_square_footage_is_calculated_from_length_and_width(self):
        page = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(page, "Room length (ft)")
        self.assertContains(page, "Room width (ft)")
        self.assertNotContains(page, 'name="square_footage"')
        self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {"room_length_ft": "18.5", "room_width_ft": "12", "action": "save"},
        )
        self.room.refresh_from_db()
        self.assertEqual((self.room.length_ft, self.room.width_ft), (Decimal("18.5"), Decimal("12.0")))
        self.assertEqual(self.room.square_footage, 222)

    def test_length_without_width_is_rejected(self):
        response = self.client.post(
            f"/audits/{self.audit.pk}/start/", {"room_length_ft": "18.5", "action": "save"}
        )
        self.assertContains(response, "Enter both the length and the width")
        self.room.refresh_from_db()
        self.assertIsNone(self.room.square_footage)

    def test_room_size_is_only_asked_on_the_first_audit(self):
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/start/"), "Room size")
        self.room.set_dimensions(Decimal("18.5"), Decimal("12"))
        later = Audit.objects.create(room=self.room, cycle_year=2027)
        self.assertNotContains(self.client.get(f"/audits/{later.pk}/start/"), "Room size")

    def test_smell_is_checked_on_the_start_step(self):
        response = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(response, "Room smell")
        self.assertContains(response, "1 unanswered")
        for label in ("OK", "Musty", "Smoke", "Other"):
            self.assertContains(response, f">{label}</button>")
        self.client.post(self.url, {"item": SMELL, "key": "room-0-smell", "result": "ok"})
        self.assertEqual(Issue.objects.count(), 0)
        self.client.post(self.url, {"item": SMELL, "key": "room-0-smell", "result": "smoke"})
        self.client.post(self.url, {"item": SMELL, "action_bucket": "work_order"})
        self.assertEqual(Finding.objects.count(), 1)
        self.assertEqual(Issue.objects.get().title, "Room smell: Smoke")
        response = self.client.get(f"/audits/{self.audit.pk}/start/")
        self.assertContains(response, "bad selected", count=1)
        self.assertNotContains(response, "1 unanswered")


class ZoneChecklistTests(FlowTestCase):
    def test_every_zone_lists_every_item_with_nothing_preselected(self):
        counts = checklist.zone_counts(self.audit)
        self.assertEqual(list(counts), ["start", "bedroom", "bathroom", "other"])
        # bathroom: 7 fixtures + 6 building elements, one check each
        self.assertEqual(counts["bathroom"], (13, 13))
        # bedroom: 27 = 9 fixtures + 10 furnishings + 7 building + squeak + bedbug
        self.assertEqual(counts["bedroom"], (27, 27))
        self.assertEqual(counts["other"], (0, 0))
        for zone in ("bedroom", "bathroom"):
            response = self.client.get(f"/audits/{self.audit.pk}/{zone}/")
            self.assertContains(response, "Unanswered</span>", count=counts[zone][0])
            self.assertContains(response, 'class="check" data-unanswered', count=counts[zone][0])
            self.assertNotContains(response, 'selected"')
        self.assertEqual(Finding.objects.count(), 0)

    def test_check_types_per_item(self):
        rows = {
            (entry.label, row.check_type)
            for entries in checklist.build_all(self.audit).values()
            for entry in entries
            for row in entry.checks
        }
        labels = {label for label, _ in rows}
        # Whether it works is part of the condition check now.
        self.assertFalse({row for row in rows if row[1] == "function"})
        # One squeak test for the whole bed, on the frame; bedbugs on the mattress.
        self.assertEqual({l for l, c in rows if c == "noise"}, {"Bed frame"})
        self.assertEqual({l for l, c in rows if c == "pest"}, {"Mattress"})
        # Consolidated rows.
        for name in ("A/C", "Heater", "Sconces and lamps", "Bedding", "Signage", "Outlet"):
            self.assertIn((name, "condition"), rows)
        for gone in ("A/C casing", "A/C filter", "Heater pilot", "Comforter", "Pillow #1",
                     "Sconce or lamp #1", "Shower handle #1"):
            self.assertNotIn(gone, labels)
        # Still separate.
        for name in ("Chair #1", "Chair #2", "Headboard", "Box spring", "Walls", "Trim", "Ceiling"):
            self.assertIn((name, "condition"), rows)
        bathroom = {e.label for e in checklist.build_zone(self.audit, "bathroom")}
        self.assertNotIn("Signage", bathroom)  # one signage row for the whole room

    def test_condition_covers_whether_it_works(self):
        page = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertNotContains(page, "Works?")
        for label in ("Not working", "Intermittent"):
            self.assertContains(page, f">{label}</button>")
        response = self.tap("TV", "intermittent")
        self.assertContains(response, "bad selected")
        self.assertContains(response, "Pick an action")
        self.act("TV", "work_order")
        self.assertEqual(Issue.objects.get().title, "TV (Bedroom): Intermittent")

    def test_tapping_a_result_saves_a_finding(self):
        response = self.tap("TV", "ok")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "good selected")
        self.assertNotContains(response, "Pick an action")
        finding = Finding.objects.get()
        self.assertEqual((finding.result, finding.fixture.name), ("ok", "TV"))
        self.assertEqual(Issue.objects.count(), 0)

    def test_squeak_and_bedbug_checks_are_pass_or_fail(self):
        response = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(response, "Squeak test (whole bed)", count=1)
        self.assertContains(response, "Bedbug check", count=1)
        self.tap("Mattress", "fail", check="pest")
        self.assertEqual(Finding.objects.get().check_type, CheckType.PEST)
        self.assertEqual(self.tap("Mattress", "worn", check="pest").status_code, 400)

    def test_other_opens_a_description_field(self):
        response = self.tap("Mirror", "other")
        self.assertContains(response, 'name="result_other"')
        entry = self.entry("Mirror")
        self.client.post(
            self.url,
            {"item": entry.key, "key": entry.checks[0].key, "result_other": "Desilvering at edge"},
        )
        self.assertEqual(Finding.objects.get().result_other, "Desilvering at edge")
        response = self.tap("Mirror", "ok")
        self.assertNotContains(response, 'name="result_other"')
        self.assertEqual(Finding.objects.get().result_other, "")

    def test_every_answered_item_has_one_note_field(self):
        for result in ("ok", "worn", "damaged", "missing", "not_working", "n_a", "other"):
            response = self.tap("TV", result)
            self.assertContains(response, 'name="notes"', count=1, msg_prefix=result)
        self.post_item("TV", notes="Remote is missing")
        self.assertEqual(self.entry("TV").notes, "Remote is missing")

    def test_clearing_a_result_marks_it_unanswered_again(self):
        self.tap("Mirror", "damaged")
        self.act("Mirror", "fix_now")
        response = self.tap("Mirror", "")
        self.assertContains(response, "Unanswered")
        self.assertEqual(Issue.objects.get().status, IssueStatus.DONE)

    def test_note_and_photos_belong_to_the_item(self):
        self.tap("Mattress", "ok")
        self.tap("Mattress", "fail", check="pest")
        self.post_item("Mattress", notes="Stain on left side")
        photo = SimpleUploadedFile("m.gif", PIXEL, content_type="image/gif")
        response = self.post_item("Mattress", photo=photo)
        self.assertContains(response, "Remove photo", count=1)
        self.assertContains(response, 'type="file"', count=1)  # one photo picker per item
        entry = self.entry("Mattress")
        self.assertEqual(entry.notes, "Stain on left side")
        self.assertEqual(len(entry.photos), 1)
        self.assertTrue(entry.photos[0].photo.name.startswith("findings/"))
        self.post_item("Mattress", remove_photo=str(entry.photos[0].pk))
        self.assertEqual(self.entry("Mattress").photos, [])

    def test_an_item_can_have_several_photos(self):
        self.tap("Sconces and lamps", "damaged")
        for name in ("left.gif", "right.gif"):
            self.post_item(
                "Sconces and lamps", photo=SimpleUploadedFile(name, PIXEL, content_type="image/gif")
            )
        # Two more chosen together from the photo library.
        response = self.client.post(
            self.url,
            {
                "item": self.entry("Sconces and lamps").key,
                "photo": [
                    SimpleUploadedFile("a.gif", PIXEL, content_type="image/gif"),
                    SimpleUploadedFile("b.gif", PIXEL, content_type="image/gif"),
                ],
            },
        )
        self.assertContains(response, "Remove photo", count=4)
        self.assertContains(response, "Add another photo")
        photos = self.entry("Sconces and lamps").photos
        self.assertEqual(len(photos), 4)
        storage, removed = photos[1].photo.storage, photos[1].photo.name
        self.post_item("Sconces and lamps", remove_photo=str(photos[1].pk))
        left = self.entry("Sconces and lamps").photos
        self.assertEqual([p.pk for p in left], [photos[0].pk, photos[2].pk, photos[3].pk])
        self.assertFalse(storage.exists(removed))  # the file goes with it
        self.act("Sconces and lamps", "fix_now")
        self.assertEqual(len(Issue.objects.get().photos), 3)

    def test_a_photo_can_only_be_removed_from_its_own_item(self):
        self.tap("TV", "damaged")
        self.tap("Mirror", "damaged")
        self.post_item("TV", photo=SimpleUploadedFile("t.gif", PIXEL, content_type="image/gif"))
        photo = self.entry("TV").photos[0]
        self.post_item("Mirror", remove_photo=str(photo.pk))
        self.assertEqual(len(self.entry("TV").photos), 1)

    def test_a_note_sent_along_with_a_tap_is_saved(self):
        self.tap("Mirror", "ok")
        entry = self.entry("Mirror")
        self.client.post(
            self.url,
            {"item": entry.key, "key": entry.checks[0].key, "result": "worn", "notes": "Scratched"},
        )
        entry = self.entry("Mirror")
        self.assertEqual((entry.anchor.result, entry.notes), ("worn", "Scratched"))

    def test_unknown_item_or_other_rooms_item_is_rejected(self):
        other = Room.objects.get(number="102").fixtures.first()
        for item in ("nope", f"fixture-{other.pk}"):
            response = self.client.post(
                self.url, {"item": item, "key": f"{item}-condition", "result": "ok"}
            )
            self.assertEqual(response.status_code, 404)
        entry = self.entry("TV")
        bad_key = self.client.post(self.url, {"item": entry.key, "key": "nope", "result": "ok"})
        self.assertEqual(bad_key.status_code, 404)

    def test_missing_expected_item_appears_and_can_be_marked_missing(self):
        self.room.building_elements.filter(element="counter").delete()
        response = self.client.get(f"/audits/{self.audit.pk}/bathroom/")
        self.assertContains(response, "Expected, not in inventory")
        self.tap("Sink counter", "missing", check="presence")
        self.act("Sink counter", "work_order")
        self.assertEqual(Issue.objects.get().title, "Sink counter (Bathroom): Missing")

    def test_flooring_type_can_be_selected_including_lvp(self):
        floor = self.room.building_elements.get(element="floor", zone="bedroom")
        response = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(response, "Flooring type", count=1)
        for option in ("Carpet", "Tile", "Tileboard", "LVP"):
            self.assertContains(response, f">{option}</button>")
        url = f"/audits/{self.audit.pk}/flooring/{floor.pk}/"
        response = self.client.post(url, {"material": "LVP"})
        self.assertContains(response, "bucket selected", count=1)
        floor.refresh_from_db()
        self.assertEqual(floor.material_or_finish, "LVP")
        self.assertEqual(self.client.post(url, {"material": "Lava"}).status_code, 400)

    def test_zone_page_has_jump_to_unanswered_controls(self):
        page = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(page, 'id="jump-top"')
        self.assertContains(page, 'id="jump-float"')
        self.assertContains(page, "nextUnanswered")

    def test_audit_can_be_saved_with_unanswered_items_and_resumed(self):
        self.tap("TV", "ok")
        self.client.post(f"/audits/{self.audit.pk}/wrapup/", {"action": "finish"})
        response = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(response, "good selected", count=1)
        total, unanswered = checklist.zone_counts(self.audit)["bedroom"]
        self.assertEqual(unanswered, total - 1)
        self.assertContains(response, f"{unanswered} unanswered")


class OneActionPerItemTests(FlowTestCase):
    def test_problem_result_asks_for_an_action_and_then_opens_an_issue(self):
        response = self.tap("Chair #2", "damaged")
        self.assertContains(response, "Pick an action")
        self.assertEqual(Issue.objects.count(), 0)
        response = self.act("Chair #2", "capex")
        self.assertContains(response, "bucket selected")
        issue = Issue.objects.get()
        self.assertEqual((issue.bucket, issue.title), ("capex", "Chair #2 (Bedroom): Damaged"))
        # Editing the saved answer back to OK closes the issue.
        self.tap("Chair #2", "ok")
        issue.refresh_from_db()
        self.assertEqual(issue.status, IssueStatus.DONE)
        self.assertEqual(Finding.objects.get().action_bucket, "")

    def test_actions_offered_are_none_fix_now_work_order_capex(self):
        response = self.tap("TV", "damaged")
        for label in ("None", "Fix now", "Work order", "Capex"):
            self.assertContains(response, f">{label}</button>")
        self.assertNotContains(response, "Monitor")
        self.assertEqual(self.act("TV", "monitor").status_code, 400)

    def test_two_problems_on_one_item_ask_for_one_action(self):
        self.tap("Mattress", "worn")
        response = self.tap("Mattress", "fail", check="pest")
        self.assertContains(response, ">Action<", count=1)
        self.assertContains(response, "Pick an action", count=1)
        response = self.act("Mattress", "work_order")
        self.assertNotContains(response, "Pick an action")
        self.assertContains(response, "bucket selected", count=1)
        self.assertEqual(
            set(Finding.objects.values_list("action_bucket", flat=True)), {"work_order"}
        )

    def test_two_problems_on_one_item_make_one_issue(self):
        self.tap("Mattress", "worn")
        self.tap("Mattress", "fail", check="pest")
        self.act("Mattress", "work_order")
        issue = Issue.objects.get()
        self.assertEqual(issue.title, "Mattress (Bedroom): Worn, Fail")
        self.assertEqual(issue.bucket, "work_order")

    def test_a_second_problem_takes_the_action_already_picked(self):
        self.tap("Mattress", "worn")
        self.act("Mattress", "capex")
        response = self.tap("Mattress", "fail", check="pest")
        self.assertNotContains(response, "Pick an action")
        issue = Issue.objects.get()
        self.assertEqual((issue.bucket, issue.title), ("capex", "Mattress (Bedroom): Worn, Fail"))

    def test_issue_survives_when_the_first_problem_is_fixed_but_another_remains(self):
        self.tap("Mattress", "worn")
        self.tap("Mattress", "fail", check="pest")
        self.act("Mattress", "fix_now")
        issue = Issue.objects.get()
        issue.priority = "high"
        issue.save()
        self.tap("Mattress", "ok")  # condition is fine after all; bedbugs remain
        issue = Issue.objects.get()
        self.assertEqual(issue.title, "Mattress (Bedroom): Fail")
        self.assertEqual((issue.status, issue.priority), (IssueStatus.OPEN, "high"))
        self.tap("Mattress", "pass", check="pest")
        self.assertEqual(Issue.objects.get().status, IssueStatus.DONE)

    def test_action_is_per_item_not_shared_between_items(self):
        self.tap("Chair #1", "damaged")
        self.act("Chair #1", "fix_now")
        response = self.tap("Chair #2", "worn")
        self.assertContains(response, "Pick an action")
        self.assertEqual(Issue.objects.count(), 1)


class NotApplicableTests(FlowTestCase):
    def test_na_is_an_answer_but_not_a_problem(self):
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), ">N/A</button>")
        response = self.tap("Mini fridge", "n_a")
        self.assertContains(response, "neutral selected")
        self.assertNotContains(response, "Pick an action")
        self.assertNotContains(response, ">Action<")
        # N/A is offered on condition checks only.
        self.assertEqual(self.tap("Mattress", "n_a", check="pest").status_code, 400)

    def test_na_hides_and_clears_the_items_other_checks(self):
        self.tap("Bed frame", "damaged")
        self.tap("Bed frame", "fail", check="noise")
        self.act("Bed frame", "capex")
        self.assertEqual(Issue.objects.get().status, IssueStatus.OPEN)

        response = self.tap("Bed frame", "n_a")
        self.assertNotContains(response, "Squeak test")
        self.assertNotContains(response, "Unanswered")
        entry = self.entry("Bed frame")
        self.assertEqual(len(entry.visible_checks), 1)
        self.assertEqual(entry.unanswered, 0)
        results = {f.check_type: (f.result, f.action_bucket) for f in Finding.objects.all()}
        self.assertEqual(results, {"condition": ("n_a", ""), "noise": ("", "")})
        self.assertEqual(Issue.objects.get().status, IssueStatus.DONE)

    def test_na_item_does_not_count_as_unanswered(self):
        total, unanswered = checklist.zone_counts(self.audit)["bedroom"]
        self.tap("Bed frame", "n_a")  # had two checks: condition and squeak
        self.assertEqual(checklist.zone_counts(self.audit)["bedroom"], (total - 1, unanswered - 2))

    def test_na_keeps_the_note_and_photo(self):
        self.tap("Mini fridge", "worn")
        self.post_item("Mini fridge", notes="Room never had one")
        self.post_item("Mini fridge", photo=SimpleUploadedFile("f.gif", PIXEL, content_type="image/gif"))
        response = self.tap("Mini fridge", "n_a")
        self.assertContains(response, 'name="notes"')
        self.assertContains(response, "Room never had one")
        self.assertContains(response, "Remove photo")
        self.assertContains(response, 'type="file"')

    def test_changing_na_back_shows_the_other_checks_again(self):
        self.tap("Bed frame", "n_a")
        response = self.tap("Bed frame", "ok")
        self.assertContains(response, "Squeak test")
        self.assertContains(response, "Unanswered", count=1)


class BeddingTests(FlowTestCase):
    def test_bedding_is_one_row_with_a_pillows_to_replace_count(self):
        page = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertContains(page, "Comforter and 2 pillows")
        self.assertNotContains(page, "Pillows to replace")  # appears once answered
        response = self.tap("Bedding", "worn")
        self.assertContains(response, "Pillows to replace", count=1)
        self.assertNotContains(self.tap("TV", "worn"), "Pillows to replace")

    def test_pillow_count_is_saved_and_shown_in_the_issue(self):
        self.tap("Bedding", "worn")
        self.act("Bedding", "fix_now")
        self.assertEqual(self.post_item("Bedding", pillows="2").status_code, 200)
        self.assertEqual(self.entry("Bedding").pillows, 2)
        finding = Finding.objects.get()
        self.assertEqual(
            (finding.measurement_label, finding.measured_value, finding.unit),
            ("Pillows to replace", Decimal("2"), "pillows"),
        )
        self.assertEqual(Issue.objects.get().title, "Bedding (Bedroom): Worn (replace 2 pillows)")
        self.post_item("Bedding", pillows="1")
        self.assertEqual(Issue.objects.get().title, "Bedding (Bedroom): Worn (replace 1 pillow)")
        self.post_item("Bedding", pillows="0")
        self.assertEqual(Issue.objects.get().title, "Bedding (Bedroom): Worn")
        self.assertEqual(self.entry("Bedding").pillows, 0)

    def test_pillow_count_is_validated_and_only_for_bedding(self):
        self.tap("Bedding", "worn")
        for bad in ("13", "-1", "lots"):
            self.assertEqual(self.post_item("Bedding", pillows=bad).status_code, 400, bad)
        self.assertEqual(self.entry("Bedding").pillows, 0)
        self.tap("TV", "worn")
        self.post_item("TV", pillows="3")
        self.assertEqual(self.entry("TV").pillows, 0)

    def test_na_clears_the_pillow_count(self):
        self.tap("Bedding", "worn")
        self.post_item("Bedding", pillows="2")
        response = self.tap("Bedding", "n_a")
        self.assertNotContains(response, "Pillows to replace")
        self.assertEqual(self.entry("Bedding").pillows, 0)

    def test_room_9_has_a_bedding_row_per_bed(self):
        audit = Audit.objects.create(room=Room.objects.get(number="9"), cycle_year=2026)
        labels = [e.label for e in checklist.build_zone(audit, "bedroom")]
        self.assertIn("Bedding #1", labels)
        self.assertIn("Bedding #2", labels)


class OtherZoneTests(FlowTestCase):
    def add(self, name):
        return self.client.post(f"/audits/{self.audit.pk}/other/add/", {"name": name})

    def test_bedroom_no_longer_has_an_add_decor_form(self):
        page = self.client.get(f"/audits/{self.audit.pk}/bedroom/")
        self.assertNotContains(page, "Add decor")
        self.assertNotContains(page, "other/add/")

    def test_items_are_added_in_the_other_zone_without_leaving_the_page(self):
        page = self.client.get(f"/audits/{self.audit.pk}/other/")
        self.assertContains(page, "Nothing added yet")
        response = self.add("Framed beach print")
        self.assertEqual(response.status_code, 200)  # a fragment, not a redirect
        self.assertContains(response, 'id="zone-items"')
        self.assertContains(response, "Framed beach print")
        item = self.room.furnishings.get(zone="other")
        self.assertEqual((item.name, item.category), ("Framed beach print", "other"))
        self.assertContains(self.client.get(f"/audits/{self.audit.pk}/other/"), "Framed beach print")
        self.assertNotContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), "Framed beach print")
        self.assertEqual(self.add("").status_code, 400)

    def test_added_items_are_checked_like_any_other(self):
        self.add("Framed beach print")
        self.assertEqual(checklist.zone_counts(self.audit)["other"], (1, 1))
        self.tap("Framed beach print", "damaged")
        self.act("Framed beach print", "fix_now")
        self.assertEqual(Issue.objects.get().title, "Framed beach print (Other): Damaged")

    def test_added_items_can_be_deleted(self):
        self.add("Framed beach print")
        self.tap("Framed beach print", "damaged")
        self.act("Framed beach print", "fix_now")
        item = self.room.furnishings.get(zone="other")
        page = self.client.get(f"/audits/{self.audit.pk}/other/")
        self.assertContains(page, "Delete this item", count=1)
        response = self.client.post(f"/audits/{self.audit.pk}/other/{item.pk}/delete/")
        self.assertContains(response, "Nothing added yet")
        self.assertFalse(self.room.furnishings.filter(zone="other").exists())
        self.assertEqual((Finding.objects.count(), Issue.objects.count()), (0, 0))

    def test_standard_items_cannot_be_deleted_from_the_audit(self):
        chair = self.room.furnishings.filter(category="chair").first()
        response = self.client.post(f"/audits/{self.audit.pk}/other/{chair.pk}/delete/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.room.furnishings.filter(category="chair").count(), 2)
        self.assertNotContains(self.client.get(f"/audits/{self.audit.pk}/bedroom/"), "Delete this item")


class WrapUpTests(FlowTestCase):
    def test_wrapup_shows_ac_numbers_without_pass_or_fail(self):
        self.client.post(
            f"/audits/{self.audit.pk}/start/",
            {"ambient_temperature_f": "88", "ac_on_time": "2026-11-10T14:00", "action": "save"},
        )
        response = self.client.post(
            f"/audits/{self.audit.pk}/wrapup/",
            {
                "ac_outflow_value": "56.5",
                "ac_outflow_time": "2026-11-10T14:20",
                "overall_notes": "Fine overall",
                "action": "save",
            },
            follow=True,
        )
        self.assertContains(response, "88.0°F")
        self.assertContains(response, "56.5°F")
        self.assertContains(response, "31.5°F")
        self.assertContains(response, "20.0 min")
        for word in ("tag pass", "tag fail", ">Pass<", ">Fail<"):
            self.assertNotContains(response, word)
        self.audit.refresh_from_db()
        self.assertEqual(self.audit.overall_notes, "Fine overall")
        self.assertIsNone(self.audit.end_time)

    def test_there_is_no_overall_rating(self):
        page = self.client.get(f"/audits/{self.audit.pk}/wrapup/")
        self.assertNotContains(page, "Overall rating")
        self.assertNotContains(page, "overall_rating")
        self.assertFalse(hasattr(self.audit, "overall_rating"))

    def test_outflow_time_defaults_to_now_and_finish_ends_the_audit(self):
        before = timezone.now() - timedelta(seconds=1)
        self.client.post(
            f"/audits/{self.audit.pk}/wrapup/", {"ac_outflow_value": "56", "action": "finish"}
        )
        self.assertGreaterEqual(ac_result(self.audit).outflow_at, before)
        self.audit.refresh_from_db()
        self.assertIsNotNone(self.audit.end_time)

    def test_an_item_with_two_problems_is_listed_once_in_the_issue_summary(self):
        self.tap("Mattress", "worn")
        self.tap("Mattress", "fail", check="pest")
        self.act("Mattress", "work_order")
        page = self.client.get(f"/audits/{self.audit.pk}/wrapup/")
        self.assertContains(page, "Issues from this audit: 1")
