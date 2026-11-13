"""A/C check: outflow air temperature compared with the outside temperature.

The A/C is switched on at the start of the audit and its outflow air is read
at wrap-up. The app shows the numbers; it does not judge pass or fail.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .models import AC_OUTFLOW_LABEL, CheckType, Finding, ItemKind

UNIT_F = "°F"


@dataclass
class ACResult:
    outside: Optional[Decimal] = None  # ambient temperature outside, °F
    outflow: Optional[Decimal] = None  # air coming out of the A/C, °F
    on_at: Optional[datetime] = None  # when the A/C was switched on
    outflow_at: Optional[datetime] = None  # when the outflow reading was taken

    @property
    def difference(self):
        """How many °F colder the outflow air is than outside (negative if warmer)."""
        if self.outside is None or self.outflow is None:
            return None
        return Decimal(self.outside) - Decimal(self.outflow)

    @property
    def minutes_running(self):
        """Minutes between switching the A/C on and the outflow reading."""
        if self.on_at is None or self.outflow_at is None:
            return None
        return round((self.outflow_at - self.on_at).total_seconds() / 60, 1)

    @property
    def recorded(self):
        return self.outflow is not None or self.on_at is not None


def reading(audit, label):
    for finding in audit.findings.all():
        if finding.check_type == CheckType.MEASUREMENT and finding.measurement_label == label:
            return finding
    return None


def ac_result(audit):
    outflow = reading(audit, AC_OUTFLOW_LABEL)
    return ACResult(
        outside=audit.ambient_temperature_f,
        outflow=outflow.measured_value if outflow else None,
        on_at=audit.ac_on_at,
        outflow_at=outflow.measured_at if outflow else None,
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


def set_outflow(audit, value, measured_at):
    """Save (or, when value is None, remove) the A/C outflow air reading."""
    return set_measurement(
        audit, AC_OUTFLOW_LABEL, value, measured_at, UNIT_F, fixture=audit.room.ac_unit()
    )
