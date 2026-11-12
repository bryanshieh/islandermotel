from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from audits.models import (
    AUTO_CLOSE_NOTE,
    ActionBucket,
    Audit,
    CheckType,
    Finding,
    Issue,
    IssueStatus,
    ItemKind,
    Room,
)


class FindingToIssueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.room = Room.objects.get(number="101")
        cls.chair = cls.room.furnishings.filter(category="chair").first()

    def setUp(self):
        self.audit = Audit.objects.create(room=self.room, cycle_year=2026)

    def finding(self, result="damaged", bucket=ActionBucket.WORK_ORDER, audit=None):
        return Finding.objects.create(
            audit=audit or self.audit,
            target_kind=ItemKind.FURNISHING,
            furnishing=self.chair,
            check_type=CheckType.CONDITION,
            result=result,
            action_bucket=bucket,
        )

    def test_problem_finding_creates_an_issue(self):
        finding = self.finding()
        issue = Issue.objects.get()
        self.assertEqual(issue.finding, finding)
        self.assertEqual(issue.room, self.room)
        self.assertEqual(issue.bucket, "work_order")
        self.assertEqual(issue.status, IssueStatus.OPEN)
        self.assertEqual(issue.date_opened, timezone.localdate())
        self.assertEqual(issue.title, "Chair #1 (Bedroom): Damaged")

    def test_each_issue_bucket_creates_an_issue(self):
        chairs = list(self.room.furnishings.filter(category="chair")) + [
            self.room.furnishings.get(category="table")
        ]
        for item, bucket in zip(
            chairs, (ActionBucket.FIX_NOW, ActionBucket.WORK_ORDER, ActionBucket.CAPEX)
        ):
            Finding.objects.create(
                audit=self.audit,
                target_kind=ItemKind.FURNISHING,
                furnishing=item,
                check_type=CheckType.CONDITION,
                result="damaged",
                action_bucket=bucket,
            )
        self.assertEqual(
            sorted(Issue.objects.values_list("bucket", flat=True)),
            ["capex", "fix_now", "work_order"],
        )

    def test_ok_finding_creates_no_issue(self):
        self.finding(result="ok", bucket="")
        self.assertEqual(Issue.objects.count(), 0)

    def test_actions_are_none_fix_now_work_order_capex(self):
        self.assertEqual(ActionBucket.values, ["none", "fix_now", "work_order", "capex"])

    def test_bucket_none_or_unset_creates_no_issue(self):
        self.finding(bucket=ActionBucket.NONE)
        self.assertEqual(Issue.objects.count(), 0)
        Finding.objects.all().delete()
        self.finding(bucket="")
        self.assertEqual(Issue.objects.count(), 0)

    def test_unanswered_finding_creates_no_issue(self):
        self.finding(result="", bucket=ActionBucket.FIX_NOW)
        self.assertEqual(Issue.objects.count(), 0)

    def test_failed_squeak_test_creates_an_issue(self):
        Finding.objects.create(
            audit=self.audit,
            target_kind=ItemKind.FURNISHING,
            furnishing=self.room.furnishings.get(category="bed_frame"),
            check_type=CheckType.NOISE,
            result="fail",
            action_bucket=ActionBucket.FIX_NOW,
        )
        self.assertEqual(Issue.objects.get().title, "Bed frame (Bedroom): Fail")

    def test_other_result_uses_the_free_text_in_the_title(self):
        finding = self.finding(result="other")
        finding.result_other = "Wobbly leg"
        finding.save()
        self.assertEqual(Issue.objects.get().title, "Chair #1 (Bedroom): Other: Wobbly leg")

    def test_editing_the_finding_updates_its_issue(self):
        finding = self.finding()
        finding.result = "worn"
        finding.action_bucket = ActionBucket.CAPEX
        finding.save()
        issue = Issue.objects.get()
        self.assertEqual(issue.bucket, "capex")
        self.assertEqual(issue.title, "Chair #1 (Bedroom): Worn")
        self.assertEqual(issue.status, IssueStatus.OPEN)

    def test_editing_the_finding_to_ok_closes_its_issue(self):
        finding = self.finding()
        finding.result = "ok"
        finding.action_bucket = ""
        finding.save()
        issue = Issue.objects.get()
        self.assertEqual(issue.status, IssueStatus.DONE)
        self.assertEqual(issue.date_resolved, timezone.localdate())
        self.assertEqual(issue.resolution_notes, AUTO_CLOSE_NOTE)

    def test_moving_the_bucket_to_none_closes_its_issue(self):
        finding = self.finding()
        finding.action_bucket = ActionBucket.NONE
        finding.save()
        self.assertEqual(Issue.objects.get().status, IssueStatus.DONE)

    def test_issue_reopens_if_the_finding_becomes_a_problem_again(self):
        finding = self.finding()
        finding.result, finding.action_bucket = "ok", ""
        finding.save()
        finding.result, finding.action_bucket = "damaged", ActionBucket.FIX_NOW
        finding.save()
        issue = Issue.objects.get()  # still one issue, not a second
        self.assertEqual(issue.status, IssueStatus.OPEN)
        self.assertIsNone(issue.date_resolved)
        self.assertEqual(issue.resolution_notes, "")
        self.assertEqual(issue.bucket, "fix_now")

    def test_a_manually_resolved_issue_is_not_reopened_by_a_finding_edit(self):
        finding = self.finding()
        issue = Issue.objects.get()
        issue.status = IssueStatus.DONE
        issue.resolution_notes = "Replaced the chair"
        issue.save()
        finding.notes = "Photo added later"
        finding.save()
        issue.refresh_from_db()
        self.assertEqual(issue.status, IssueStatus.DONE)
        self.assertEqual(issue.resolution_notes, "Replaced the chair")

    def test_saving_twice_keeps_one_issue_and_its_edits(self):
        finding = self.finding()
        issue = Issue.objects.get()
        issue.priority = "safety"
        issue.cost_estimate = 120
        issue.status = IssueStatus.SCHEDULED
        issue.save()
        finding.save()
        issue = Issue.objects.get()
        self.assertEqual(issue.priority, "safety")
        self.assertEqual(issue.cost_estimate, 120)
        self.assertEqual(issue.status, IssueStatus.SCHEDULED)

    def test_a_new_audit_cycle_opens_a_new_issue_for_the_same_item(self):
        self.finding()
        next_year = Audit.objects.create(room=self.room, cycle_year=2027)
        self.finding(audit=next_year)
        self.assertEqual(Issue.objects.count(), 2)
        self.assertEqual(
            sorted(Issue.objects.values_list("finding__audit__cycle_year", flat=True)),
            [2026, 2027],
        )
        self.assertTrue(all(i.status == IssueStatus.OPEN for i in Issue.objects.all()))

    def test_missing_expected_item_creates_an_issue(self):
        standard = self.room.room_type.standards.get(name="Sink counter")
        self.room.building_elements.filter(element="counter").delete()
        Finding.objects.create(
            audit=self.audit,
            target_kind=ItemKind.BUILDING,
            standard=standard,
            check_type=CheckType.PRESENCE,
            result="missing",
            action_bucket=ActionBucket.WORK_ORDER,
        )
        self.assertEqual(Issue.objects.get().title, "Sink counter (Bathroom): Missing")

    def test_several_problems_on_one_item_share_one_issue(self):
        bed = self.room.furnishings.get(category="mattress")

        def check(check_type, result, bucket=""):
            return Finding.objects.create(
                audit=self.audit,
                target_kind=ItemKind.FURNISHING,
                furnishing=bed,
                check_type=check_type,
                result=result,
                action_bucket=bucket,
            )

        check(CheckType.PEST, "fail")  # answered first, no action yet
        self.assertEqual(Issue.objects.count(), 0)
        condition = check(CheckType.CONDITION, "worn", ActionBucket.CAPEX)
        check(CheckType.NOISE, "pass")
        issue = Issue.objects.get()
        # Listed in check order (condition before bedbug), good results left out.
        self.assertEqual(issue.title, "Mattress (Bedroom): Worn, Fail")
        self.assertEqual((issue.bucket, issue.finding), ("capex", condition))
        # A different item in the same audit gets its own issue.
        self.finding()
        self.assertEqual(Issue.objects.count(), 2)

    def test_issue_notes_and_photos_come_from_all_of_the_items_findings(self):
        finding = self.finding()
        finding.notes = "Leg split"
        finding.save()
        self.assertEqual(Issue.objects.get().notes_text, "Leg split")
        self.assertEqual(Issue.objects.get().photos, [])

    def test_not_applicable_is_not_a_problem(self):
        self.finding(result="n_a", bucket=ActionBucket.FIX_NOW)
        self.assertEqual(Issue.objects.count(), 0)

    def test_problem_smell_creates_a_room_level_issue(self):
        Finding.objects.create(
            audit=self.audit, check_type=CheckType.SMELL, result="musty",
            action_bucket=ActionBucket.WORK_ORDER,
        )
        issue = Issue.objects.get()
        self.assertEqual((issue.title, issue.room), ("Room smell: Musty", self.room))
