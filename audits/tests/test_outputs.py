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
        problem("9", 2026, "none", name="Toilet")  # no issue
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


class DashboardTests(OutputTestCase):
    def test_defaults_to_the_latest_cycle(self):
        context = self.client.get("/dashboard/").context
        self.assertEqual(context["year"], 2026)
        self.assertEqual(context["years"], [2026, 2025])
        self.assertEqual(self.client.get("/dashboard/?cycle=1999").context["year"], 2026)

    def test_counts_by_bucket_and_room_type_are_absolute_numbers(self):
        response = self.client.get("/dashboard/")
        context = response.context
        self.assertEqual(
            [(value, count) for value, _, count in context["bucket_rows"]],
            [("fix_now", 1), ("work_order", 1), ("capex", 2)],
        )
        self.assertEqual(
            {rt.name: count for rt, count in context["type_rows"]},
            {"SML": 1, "STD": 2, "LRG": 0, "XLRG": 1},
        )
        self.assertEqual(context["issue_total"], 4)
        body = response.content.decode().split("<main", 1)[1]
        self.assertNotIn("%", body)

    def test_totals_match_the_issue_list(self):
        context = self.client.get("/dashboard/").context
        listed = self.client.get("/issues/?cycle=2026").context["issues"]
        self.assertEqual(context["issue_total"], len(listed))
        for value, _, count in context["bucket_rows"]:
            rows = self.client.get(f"/issues/?cycle=2026&bucket={value}").context["issues"]
            self.assertEqual(count, len(rows))
        for room_type, count in context["type_rows"]:
            rows = self.client.get(f"/issues/?cycle=2026&room_type={room_type.id}").context["issues"]
            self.assertEqual(count, len(rows))

    def test_cycle_selector_switches_year(self):
        context = self.client.get("/dashboard/?cycle=2025").context
        self.assertEqual(context["year"], 2025)
        self.assertEqual(context["issue_total"], 1)
        self.assertEqual([row["room"].number for row in context["ac_rows"]], ["7"])

    def test_ac_results_per_room(self):
        context = self.client.get("/dashboard/").context
        rows = {row["room"].number: row["ac"] for row in context["ac_rows"]}
        self.assertEqual(list(rows), ["7", "9", "101"])
        self.assertEqual(
            (rows["101"].start_value, rows["101"].end_value, rows["101"].elapsed_minutes, rows["101"].drop),
            (Decimal("78.0"), Decimal("55.0"), 9.0, Decimal("23.0")),
        )
        self.assertEqual({n: r.status for n, r in rows.items()}, {"101": "pass", "7": "fail", "9": "incomplete"})
        self.assertEqual(
            (context["ac_pass"], context["ac_fail"], context["ac_incomplete"]), (1, 1, 1)
        )

    def test_storage_is_excluded(self):
        storage = Room.objects.get(is_storage=True)
        audit = Audit.objects.create(room=storage, cycle_year=2026)
        Finding.objects.create(
            audit=audit, target_kind=ItemKind.FURNISHING, check_type=CheckType.CONDITION,
            result="damaged", action_bucket="capex",
        )
        context = self.client.get("/dashboard/").context
        self.assertEqual(context["issue_total"], 4)
        self.assertNotIn("00", [row["room"].number for row in context["ac_rows"]])
        self.assertEqual(len(self.client.get("/issues/").context["issues"]), 5)

    def test_empty_dashboard(self):
        Audit.objects.all().delete()
        self.assertContains(self.client.get("/dashboard/"), "No audits yet")
