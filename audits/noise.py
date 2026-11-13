"""Noise measurements: peak dB outside the room and inside it, from the bed."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from .ac import reading, set_measurement
from .models import NOISE_INSIDE_LABEL, NOISE_OUTSIDE_LABEL

UNIT_DB = "dB"
NOISE_LABELS = {"outside": NOISE_OUTSIDE_LABEL, "inside": NOISE_INSIDE_LABEL}


@dataclass
class NoiseResult:
    outside: Optional[Decimal] = None
    inside: Optional[Decimal] = None

    @property
    def recorded(self):
        return self.outside is not None or self.inside is not None

    @property
    def reduction(self):
        """How many dB quieter it is inside than outside; None until both exist."""
        if self.outside is None or self.inside is None:
            return None
        return Decimal(self.outside) - Decimal(self.inside)


def noise_result(audit):
    outside, inside = reading(audit, NOISE_OUTSIDE_LABEL), reading(audit, NOISE_INSIDE_LABEL)
    return NoiseResult(
        outside=outside.measured_value if outside else None,
        inside=inside.measured_value if inside else None,
    )


def set_noise(audit, where, value):
    """Save the peak dB reading for "outside" or "inside"; None removes it.

    The time is recorded when the value is first entered or changed.
    """
    label = NOISE_LABELS[where]
    existing = reading(audit, label)
    if existing and value is not None and existing.measured_value == value:
        return existing
    return set_measurement(audit, label, value, timezone.now(), UNIT_DB)
