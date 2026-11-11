"""Builds the list of items and checks shown in each audit zone.

The list is computed from the room's inventory and its room type standard each
time, so inventory added mid-audit (for example decor) shows up straight away.
A Finding row is only created when an item is first answered; an item with no
Finding, or a Finding with a blank result, is unanswered.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    AC_UNIT_NAME,
    GOOD_RESULTS,
    NOT_APPLICABLE,
    BuildingElementType,
    RESULT_OPTIONS,
    CheckType,
    Finding,
    FixtureCategory,
    FurnishingCategory,
    ItemKind,
    ItemStatus,
    Zone,
)

AUDIT_ZONES = [Zone.BEDROOM, Zone.BATHROOM]

# The room-level smell check on the Start step.
SMELL_KEY = "room-0-smell"

CHECK_LABELS = {
    CheckType.CONDITION: "Condition",
    CheckType.FUNCTION: "Works?",
    CheckType.NOISE: "Squeak test",
    CheckType.PEST: "Bedbug check",
    CheckType.PRESENCE: "Present?",
    CheckType.SMELL: "Smell",
}

# Fixtures that get a "does it work" check on top of the condition check.
FUNCTION_CATEGORIES = {
    FixtureCategory.HEATER,
    FixtureCategory.TV,
    FixtureCategory.LIGHT,
    FixtureCategory.OUTLET,
    FixtureCategory.SINK,
    FixtureCategory.SHOWER,
    FixtureCategory.TOILET,
    FixtureCategory.SMOKE_DETECTOR,
    FixtureCategory.SHOWER_HANDLE,
    FixtureCategory.MINI_FRIDGE,
}
SQUEAK_CATEGORIES = {FurnishingCategory.BED_FRAME, FurnishingCategory.MATTRESS}
BEDBUG_CATEGORIES = {FurnishingCategory.MATTRESS}

TARGET_FIELDS = {
    ItemKind.FURNISHING: "furnishing",
    ItemKind.FIXTURE: "fixture",
    ItemKind.BUILDING: "building_element",
}


def checks_for(item):
    """Check types for one inventory record."""
    checks = [CheckType.CONDITION]
    if item.kind == ItemKind.FIXTURE:
        is_ac_unit = item.category == FixtureCategory.HVAC and item.name == AC_UNIT_NAME
        if item.category in FUNCTION_CATEGORIES or is_ac_unit:
            checks.append(CheckType.FUNCTION)
    elif item.kind == ItemKind.FURNISHING:
        if item.category in SQUEAK_CATEGORIES:
            checks.append(CheckType.NOISE)
        if item.category in BEDBUG_CATEGORIES:
            checks.append(CheckType.PEST)
    return checks


def finding_key(finding):
    """The checklist key a saved finding answers, or None for measurements."""
    if finding.check_type == CheckType.MEASUREMENT:
        return None
    if finding.check_type == CheckType.SMELL:
        return SMELL_KEY
    for prefix, target_id in (
        ("furnishing", finding.furnishing_id),
        ("fixture", finding.fixture_id),
        ("building_element", finding.building_element_id),
        ("standard", finding.standard_id),
    ):
        if target_id:
            return f"{prefix}-{target_id}-{finding.check_type}"
    return None


@dataclass
class CheckRow:
    key: str
    check_type: str
    target_kind: str
    target_field: Optional[str]
    target: object
    finding: Optional[Finding] = None

    @property
    def label(self):
        return CHECK_LABELS[self.check_type]

    @property
    def dom_id(self):
        return f"chk-{self.key}"

    @property
    def result(self):
        return self.finding.result if self.finding else ""

    @property
    def buttons(self):
        """(value, label, css class) for each result option."""

        def css(value):
            if value == NOT_APPLICABLE:
                return "neutral"
            return "good" if value in GOOD_RESULTS else "bad"

        return [(value, label, css(value)) for value, label in RESULT_OPTIONS[self.check_type]]

    def get_or_build_finding(self, audit):
        if self.finding is None:
            target = {self.target_field: self.target} if self.target_field else {}
            self.finding = Finding(
                audit=audit, target_kind=self.target_kind, check_type=self.check_type, **target
            )
        return self.finding


@dataclass
class ItemEntry:
    label: str
    note: str = ""
    absent: bool = False
    checks: list = field(default_factory=list)
    item: object = None

    @property
    def is_floor(self):
        """Flooring gets one-tap flooring type buttons."""
        return (
            self.item is not None
            and self.item.kind == ItemKind.BUILDING
            and self.item.element == BuildingElementType.FLOOR
        )

    @property
    def can_delete(self):
        """Decor is added during an audit, so it can be deleted there too."""
        return (
            self.item is not None
            and self.item.kind == ItemKind.FURNISHING
            and self.item.category == FurnishingCategory.DECOR
        )


def build_zone(audit, zone, findings=None):
    """Every item to answer in one zone, in walk-through order."""
    room = audit.room
    if findings is None:
        findings = {finding_key(f): f for f in audit.findings.all()}

    groups = [
        list(room.fixtures.filter(zone=zone, status=ItemStatus.IN_SERVICE)),
        list(room.furnishings.filter(zone=zone, status=ItemStatus.IN_SERVICE)),
        list(room.building_elements.filter(zone=zone)),
    ]
    entries = []
    present = Counter()
    for items in groups:
        totals = Counter((i.category_code, i.name) for i in items)
        seen = Counter()
        for item in items:
            ident = (item.category_code, item.name)
            seen[ident] += 1
            present[(item.kind, item.category_code, item.name)] += 1
            label = item.base_label
            if totals[ident] > 1:
                label = f"{label} #{seen[ident]}"
            field_name = TARGET_FIELDS[item.kind]
            entry = ItemEntry(label=label, note=item.notes, item=item)
            for check in checks_for(item):
                key = f"{field_name}-{item.id}-{check}"
                entry.checks.append(
                    CheckRow(key, check, item.kind, field_name, item, findings.get(key))
                )
            entries.append(entry)

    # Items the standard expects but the room does not have, so they can be
    # marked missing.
    if room.room_type_id:
        for standard in room.room_type.standards.filter(zone=zone):
            have = present[(standard.item_kind, standard.category, standard.name)]
            if have < standard.expected_quantity:
                key = f"standard-{standard.id}-{CheckType.PRESENCE}"
                entries.append(
                    ItemEntry(
                        label=standard.name,
                        note=f"Standard expects {standard.expected_quantity}, room has {have}.",
                        absent=True,
                        checks=[
                            CheckRow(
                                key,
                                CheckType.PRESENCE,
                                standard.item_kind,
                                "standard",
                                standard,
                                findings.get(key),
                            )
                        ],
                    )
                )
    return entries


def smell_row(audit, findings=None):
    """The room-level smell check shown on the Start step."""
    if findings is None:
        findings = {finding_key(f): f for f in audit.findings.all()}
    return CheckRow(SMELL_KEY, CheckType.SMELL, "", None, None, findings.get(SMELL_KEY))


def build_all(audit):
    """{zone: [ItemEntry, ...]} for the audited zones."""
    findings = {finding_key(f): f for f in audit.findings.all()}
    return {zone: build_zone(audit, zone, findings) for zone in AUDIT_ZONES}


def find_row(audit, key):
    if key == SMELL_KEY:
        return smell_row(audit)
    for entries in build_all(audit).values():
        for entry in entries:
            for row in entry.checks:
                if row.key == key:
                    return row
    return None


def zone_counts(audit):
    """{step: (total checks, unanswered checks)} for Start and each zone."""
    counts = {"start": (1, 0 if smell_row(audit).result else 1)}
    for zone, entries in build_all(audit).items():
        rows = [row for entry in entries for row in entry.checks]
        counts[zone] = (len(rows), sum(1 for row in rows if not row.result))
    return counts
