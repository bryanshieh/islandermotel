from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from audits.ac import ACResult, ac_result, set_outflow
from audits.models import AC_OUTFLOW_LABEL, Audit, CheckType, Issue, Room

T0 = timezone.make_aware(datetime(2026, 11, 10, 14, 0))


class ACCalculationTests(TestCase):
    def test_difference_is_outside_minus_outflow(self):
        r = ACResult(outside=Decimal("88.0"), outflow=Decimal("56.5"))
        self.assertEqual(r.difference, Decimal("31.5"))

    def test_difference_is_negative_when_outflow_is_warmer(self):
        self.assertEqual(ACResult(Decimal("60"), Decimal("65")).difference, Decimal("-5"))

    def test_minutes_running_is_from_ac_on_to_the_outflow_reading(self):
        r = ACResult(on_at=T0, outflow_at=T0 + timedelta(minutes=18, seconds=30))
        self.assertEqual(r.minutes_running, 18.5)

    def test_missing_pieces_give_no_number(self):
        self.assertIsNone(ACResult(outside=Decimal("88")).difference)
        self.assertIsNone(ACResult(outflow=Decimal("56")).difference)
        self.assertIsNone(ACResult(on_at=T0).minutes_running)
        self.assertIsNone(ACResult(outflow_at=T0).minutes_running)
        self.assertFalse(ACResult().recorded)

    def test_there_is_no_pass_or_fail(self):
        r = ACResult(Decimal("88"), Decimal("56"), T0, T0 + timedelta(minutes=5))
        self.assertFalse(hasattr(r, "passed"))
        self.assertFalse(hasattr(r, "status"))


class ACReadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.room = Room.objects.get(number="101")

    def test_result_combines_the_audit_and_the_outflow_finding(self):
        audit = Audit.objects.create(
            room=self.room, cycle_year=2026, ambient_temperature_f=Decimal("88.0"), ac_on_at=T0
        )
        set_outflow(audit, Decimal("56.0"), T0 + timedelta(minutes=20))

        finding = audit.findings.get()
        self.assertEqual(finding.check_type, CheckType.MEASUREMENT)
        self.assertEqual(finding.measurement_label, AC_OUTFLOW_LABEL)
        self.assertEqual(finding.fixture, self.room.ac_unit())
        self.assertEqual(finding.unit, "°F")

        r = ac_result(audit)
        self.assertEqual((r.outside, r.outflow), (Decimal("88.0"), Decimal("56.0")))
        self.assertEqual(r.difference, Decimal("32.0"))
        self.assertEqual(r.minutes_running, 20.0)
        self.assertEqual(Issue.objects.count(), 0)  # readings never open issues

    def test_saving_the_reading_again_updates_it_and_blank_removes_it(self):
        audit = Audit.objects.create(room=self.room, cycle_year=2026)
        set_outflow(audit, Decimal("56.0"), T0)
        set_outflow(audit, Decimal("58.0"), T0)
        self.assertEqual(audit.findings.count(), 1)
        self.assertEqual(ac_result(audit).outflow, Decimal("58.0"))
        self.assertIsNone(ac_result(audit).difference)  # no outside temperature yet
        set_outflow(audit, None, None)
        self.assertEqual(audit.findings.count(), 0)
