"""A/C test: supply-air temperature must drop at least 20°F within 10 minutes."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .models import AC_END_LABEL, AC_START_LABEL, CheckType, Finding, ItemKind

AC_MIN_DROP_F = Decimal("20")
AC_MAX_MINUTES = 10
UNIT_F = "°F"


@dataclass
class ACResult:
    start_value: Optional[Decimal] = None
    start_at: Optional[datetime] = None
    end_value: Optional[Decimal] = None
    end_at: Optional[datetime] = None

    @property
    def complete(self):
        return None not in (self.start_value, self.start_at, self.end_value, self.end_at)

    @property
    def elapsed_minutes(self):
        """Minutes between the two readings, to one decimal place."""
        if self.start_at is None or self.end_at is None:
            return None
        return round((self.end_at - self.start_at).total_seconds() / 60, 1)

    @property
    def drop(self):
        """Temperature drop in °F (positive when the air got colder)."""
        if self.start_value is None or self.end_value is None:
            return None
        return Decimal(self.start_value) - Decimal(self.end_value)

    @property
    def passed(self):
        """True or False once both readings exist; None while incomplete."""
        if not self.complete:
            return None
        seconds = (self.end_at - self.start_at).total_seconds()
        return 0 <= seconds <= AC_MAX_MINUTES * 60 and self.drop >= AC_MIN_DROP_F

    @property
    def status(self):
        return {True: "pass", False: "fail", None: "incomplete"}[self.passed]


def reading(audit, label):
    for finding in audit.findings.all():
        if finding.check_type == CheckType.MEASUREMENT and finding.measurement_label == label:
            return finding
    return None


def ac_result(audit):
    """Build the A/C result for an audit from its two measurement findings."""
    start, end = reading(audit, AC_START_LABEL), reading(audit, AC_END_LABEL)
    return ACResult(
        start_value=start.measured_value if start else None,
        start_at=start.measured_at if start else None,
        end_value=end.measured_value if end else None,
        end_at=end.measured_at if end else None,
    )


def set_measurement(audit, label, value, measured_at, unit, fixture=None):
    """Create, update or (when value is None) remove one measurement finding.

    With a fixture the measurement is about that fixture; without one it is
    about the room as a whole.
    """
    finding = Finding.objects.filter(
        audit=audit, check_type=CheckType.MEASUREMENT, measurement_label=label
    ).first()
    if value is None:
        if finding:
            finding.delete()
        return None
    if finding is None:
        finding = Finding(
            audit=audit,
            target_kind=ItemKind.FIXTURE if fixture else "",
            fixture=fixture,
            check_type=CheckType.MEASUREMENT,
            measurement_label=label,
        )
    finding.measured_value = value
    finding.unit = unit
    finding.measured_at = measured_at
    finding.save()
    return finding


def set_reading(audit, label, value, measured_at):
    """Create, update or (when value is None) remove one A/C reading."""
    return set_measurement(
        audit, label, value, measured_at, UNIT_F, fixture=audit.room.ac_unit()
    )
