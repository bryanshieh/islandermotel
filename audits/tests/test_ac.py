from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from audits.ac import ACResult, ac_result, set_reading
from audits.models import AC_END_LABEL, AC_START_LABEL, Audit, CheckType, Issue, Room

T0 = timezone.make_aware(datetime(2026, 11, 10, 14, 0))


def result(start, end, minutes):
    return ACResult(
        start_value=Decimal(start),
        start_at=T0,
        end_value=Decimal(end),
        end_at=T0 + timedelta(minutes=minutes),
    )


class ACCalculationTests(TestCase):
    def test_elapsed_and_drop_are_calculated(self):
        r = result("78.5", "55.0", 8)
        self.assertEqual(r.elapsed_minutes, 8.0)
        self.assertEqual(r.drop, Decimal("23.5"))
        self.assertTrue(r.passed)
        self.assertEqual(r.status, "pass")

    def test_exactly_20_degrees_in_exactly_10_minutes_passes(self):
        self.assertTrue(result("75", "55", 10).passed)

    def test_drop_under_20_fails(self):
        r = result("75", "55.1", 5)
        self.assertEqual(r.drop, Decimal("19.9"))
        self.assertFalse(r.passed)
        self.assertEqual(r.status, "fail")

    def test_over_10_minutes_fails_even_with_a_big_drop(self):
        self.assertFalse(result("80", "50", 11).passed)

    def test_one_second_over_10_minutes_fails(self):
        r = ACResult(Decimal("80"), T0, Decimal("50"), T0 + timedelta(minutes=10, seconds=1))
        self.assertFalse(r.passed)

    def test_temperature_rise_fails(self):
        r = result("60", "70", 5)
        self.assertEqual(r.drop, Decimal("-10"))
        self.assertFalse(r.passed)

    def test_end_before_start_fails(self):
        self.assertFalse(result("80", "50", -3).passed)

    def test_incomplete_test_is_neither_pass_nor_fail(self):
        r = ACResult(start_value=Decimal("78"), start_at=T0)
        self.assertFalse(r.complete)
        self.assertIsNone(r.passed)
        self.assertIsNone(r.drop)
        self.assertIsNone(r.elapsed_minutes)
        self.assertEqual(r.status, "incomplete")


class ACReadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.room = Room.objects.get(number="101")

    def test_two_measurement_findings_on_the_ac_fixture(self):
        audit = Audit.objects.create(room=self.room, cycle_year=2026)
        set_reading(audit, AC_START_LABEL, Decimal("78.0"), T0)
        set_reading(audit, AC_END_LABEL, Decimal("56.0"), T0 + timedelta(minutes=9))

        readings = audit.findings.filter(check_type=CheckType.MEASUREMENT)
        self.assertEqual(readings.count(), 2)
        for finding in readings:
            self.assertEqual(finding.fixture, self.room.ac_unit())
            self.assertEqual(finding.unit, "°F")
            self.assertIsNotNone(finding.measured_at)

        r = ac_result(audit)
        self.assertEqual(r.drop, Decimal("22.0"))
        self.assertEqual(r.elapsed_minutes, 9.0)
        self.assertTrue(r.passed)
        self.assertEqual(Issue.objects.count(), 0)  # readings never open issues

    def test_saving_a_reading_again_updates_it(self):
        audit = Audit.objects.create(room=self.room, cycle_year=2026)
        set_reading(audit, AC_START_LABEL, Decimal("78.0"), T0)
        set_reading(audit, AC_START_LABEL, Decimal("80.0"), T0)
        self.assertEqual(audit.findings.count(), 1)
        self.assertEqual(ac_result(audit).start_value, Decimal("80.0"))
        self.assertIsNone(ac_result(audit).passed)

    def test_clearing_a_reading_removes_it(self):
        audit = Audit.objects.create(room=self.room, cycle_year=2026)
        set_reading(audit, AC_START_LABEL, Decimal("78.0"), T0)
        set_reading(audit, AC_START_LABEL, None, None)
        self.assertEqual(audit.findings.count(), 0)
