import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from audits.ac import set_reading
from audits.models import (
    AC_END_LABEL,
    AC_START_LABEL,
    Audit,
    CheckType,
    Finding,
    Issue,
    ItemKind,
    Room,
    RoomType,
)

T0 = timezone.make_aware(datetime(2026, 11, 10, 14, 0))


class OutputTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.user = User.objects.create_superuser("bryan", "", "pw")

        def problem(number, year, bucket, name="TV", result="damaged"):
            room = Room.objects.get(number=number)
            audit, _ = Audit.objects.get_or_create(room=room, cycle_year=year)
            return Finding.objects.create(
                audit=audit,
                target_kind=ItemKind.FIXTURE,
                fixture=room.fixtures.filter(name=name).first(),
                check_type=CheckType.CONDITION,
                result=result,
                action_bucket=bucket,
            )

        # 2026: 101 (STD) fix_now + capex, 7 (SML) work_order, 9 (XLRG) capex
        problem("101", 2026, "fix_now")
        problem("101", 2026, "capex", name="Toilet")
        problem("7", 2026, "work_order")
        problem("9", 2026, "capex")
        problem("9", 2026, "monitor", name="Toilet")  # no issue
        # 2025: one older issue in room 7
        problem("7", 2025, "fix_now")

        # A/C: 101 passes, 7 fails, 9 has only a first reading
        for number, end_value in (("101", "55"), ("7", "62")):
            audit = Audit.objects.get(room__number=number, cycle_year=2026)
            set_reading(audit, AC_START_LABEL, Decimal("78"), T0)
            set_reading(audit, AC_END_LABEL, Decimal(end_value), T0 + timedelta(minutes=9))
        set_reading(Audit.objects.get(room__number="9", cycle_year=2026), AC_START_LABEL, Decimal("80"), T0)

    def setUp(self):
        self.client.force_login(self.user)


class IssueListTests(OutputTestCase):
    def rooms(self, query=""):
        return [issue.room.number for issue in self.client.get(f"/issues/{query}").context["issues"]]

    def test_lists_every_issue_sorted_by_room_number(self):
        self.assertEqual(self.rooms(), ["7", "7", "9", "101", "101"])

    def test_filters(self):
        std = RoomType.objects.get(name="STD").pk
        room7 = Room.objects.get(number="7").pk
        self.assertEqual(self.rooms("?bucket=capex"), ["9", "101"])
        self.assertEqual(self.rooms(f"?room={room7}"), ["7", "7"])
        self.assertEqual(self.rooms(f"?room_type={std}"), ["101", "101"])
        self.assertEqual(self.rooms(f"?room_type={std}&bucket=fix_now"), ["101"])
        self.assertEqual(self.rooms("?cycle=2025"), ["7"])
        self.assertEqual(self.rooms("?status=done"), [])
        Issue.objects.filter(room__number="9").update(status="scheduled")
        self.assertEqual(self.rooms("?status=scheduled"), ["9"])
        self.assertEqual(self.rooms("?bucket=bogus&room=x"), ["7", "7", "9", "101", "101"])

    def test_csv_export_matches_the_filtered_view(self):
        response = self.client.get("/issues/export.csv?bucket=capex")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][:7], ["Room", "Room type", "Item", "Bucket", "Priority", "Status", "Cost estimate"])
        self.assertEqual([row[0] for row in rows[1:]], ["9", "101"])
        self.assertEqual(rows[2][:6], ["101", "STD", "Toilet (Bathroom): Damaged", "Capex", "Medium", "Open"])
        self.assertEqual(rows[2][7], "2026 annual")
        self.assertEqual(len(list(csv.reader(io.StringIO(self.client.get("/issues/export.csv").content.decode())))), 6)

    def test_status_can_be_changed_from_the_list(self):
        issue = Issue.objects.filter(room__number="9").get()
        response = self.client.post(f"/issues/{issue.pk}/status/", {"status": "done"})
        self.assertContains(response, f'id="issue-{issue.pk}"')
        issue.refresh_from_db()
        self.assertEqual(issue.status, "done")
        self.assertEqual(issue.date_resolved, timezone.localdate())
        self.assertEqual(self.client.post(f"/issues/{issue.pk}/status/", {"status": "x"}).status_code, 400)

    def test_issue_fields_can_be_edited(self):
        issue = Issue.objects.filter(room__number="9").get()
        response = self.client.post(
            f"/issues/{issue.pk}/edit/?back=bucket%3Dcapex",
            {
                "status": "scheduled",
                "priority": "safety",
                "cost_estimate": "450.00",
                "date_resolved": "",
                "resolution_notes": "Vendor booked",
            },
        )
        self.assertRedirects(response, "/issues/?bucket=capex")
        issue.refresh_from_db()
        self.assertEqual(
            (issue.status, issue.priority, issue.cost_estimate, issue.resolution_notes),
            ("scheduled", "safety", Decimal("450.00"), "Vendor booked"),
        )
