"""Data model for the Islander Motel room audit app.

Things (rooms and their inventory) are kept apart from observations (audits
and findings). Condition is never stored on an inventory item; it is a Finding
on a dated Audit, so history builds up on its own.
"""

from decimal import ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


class Zone(models.TextChoices):
    BEDROOM = "bedroom", "Bedroom"
    BATHROOM = "bathroom", "Bathroom"
    EXTERIOR = "exterior", "Exterior"
    # Items added during an audit that are not on the standard list (decor etc.).
    OTHER = "other", "Other"


class ItemKind(models.TextChoices):
    FURNISHING = "furnishing", "Furnishing"
    FIXTURE = "fixture", "Fixture"
    BUILDING = "building", "Building"


class FurnishingCategory(models.TextChoices):
    BED_FRAME = "bed_frame", "Bed frame"
    HEADBOARD = "headboard", "Headboard"
    MATTRESS = "mattress", "Mattress"
    BOX_SPRING = "box_spring", "Box spring"
    COMFORTER = "comforter", "Comforter"
    PILLOW = "pillow", "Pillow"
    BEDDING = "bedding", "Bedding"
    CHAIR = "chair", "Chair"
    TABLE = "table", "Table"
    DRESSER = "dresser", "Dresser"
    DECOR = "decor", "Decor"
    OTHER = "other", "Other"


class FixtureCategory(models.TextChoices):
    HVAC = "hvac", "HVAC"
    HEATER = "heater", "Heater"
    TV = "tv", "TV"
    LIGHT = "light", "Light"
    OUTLET = "outlet", "Outlet"
    SINK = "sink", "Sink"
    SHOWER = "shower", "Shower"
    TOILET = "toilet", "Toilet"
    MIRROR = "mirror", "Mirror"
    SMOKE_DETECTOR = "smoke_detector", "Smoke detector"
    TOWEL_RACK = "towel_rack", "Towel rack"
    MINI_FRIDGE = "mini_fridge", "Mini fridge"
    SHOWER_HANDLE = "shower_handle", "Shower handle"
    OTHER = "other", "Other"


class BuildingElementType(models.TextChoices):
    FLOOR = "floor", "Floor"
    CEILING = "ceiling", "Ceiling"
    WALL = "wall", "Wall or drywall"
    DOOR = "door", "Door"
    LOCK = "lock", "Lock"
    HINGE = "hinge", "Hinge"
    WINDOW = "window", "Window"
    TRIM = "trim", "Trim"
    THRESHOLD = "threshold", "Threshold"
    COUNTER = "counter", "Counter"
    SIGNAGE = "signage", "Signage"
    OTHER = "other", "Other"


CATEGORY_LABELS = {
    ItemKind.FURNISHING: dict(FurnishingCategory.choices),
    ItemKind.FIXTURE: dict(FixtureCategory.choices),
    ItemKind.BUILDING: dict(BuildingElementType.choices),
}

# Flooring types offered as one-tap choices during the audit.
FLOORING_TYPES = ["Carpet", "Tile", "Tileboard", "LVP"]

# The A/C unit that the two supply-air readings are attached to is the HVAC
# fixture with this name (the casing and filter are separate HVAC fixtures).
AC_UNIT_NAME = "A/C"


def room_sort_key(number):
    """Sort room numbers numerically ("7" before "101"), text last."""
    return (0, int(number), "") if str(number).isdigit() else (1, 0, str(number))


class Property(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    zip_code = models.CharField("zip", max_length=10, blank=True)
    lot_size_sqft = models.PositiveIntegerField("lot size (sq ft)", null=True, blank=True)
    building_size_sqft = models.PositiveIntegerField(
        "building size (sq ft)", null=True, blank=True
    )
    year_built = models.PositiveIntegerField(null=True, blank=True)
    unit_count = models.PositiveIntegerField(default=34, help_text="Guest rooms")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name


class RoomType(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="room_types")
    name = models.CharField(max_length=20)
    default_square_footage = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["property", "name"], name="unique_room_type_name")
        ]

    def __str__(self):
        return self.name


class RoomStandard(models.Model):
    """What a room of this type should contain; inventory is generated from it."""

    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="standards")
    item_kind = models.CharField(max_length=20, choices=ItemKind.choices)
    category = models.CharField(
        "category or element",
        max_length=30,
        help_text="A furnishing category, fixture category or building element code.",
    )
    zone = models.CharField(max_length=20, choices=Zone.choices)
    name = models.CharField(max_length=100, help_text="Name shown in the audit, e.g. A/C filter")
    expected_quantity = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.room_type} {self.get_zone_display()}: {self.name} x{self.expected_quantity}"

    def inventory_queryset(self, room):
        """Inventory records in the room that satisfy this standard row."""
        if self.item_kind == ItemKind.FURNISHING:
            qs = room.furnishings.filter(category=self.category, status=ItemStatus.IN_SERVICE)
        elif self.item_kind == ItemKind.FIXTURE:
            qs = room.fixtures.filter(category=self.category, status=ItemStatus.IN_SERVICE)
        else:
            qs = room.building_elements.filter(element=self.category)
        return qs.filter(zone=self.zone, name=self.name)


class RoomStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    OUT_OF_SERVICE = "out_of_service", "Out of service"
    UNDER_RENOVATION = "under_renovation", "Under renovation"


class Room(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rooms")
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        related_name="rooms",
        null=True,
        blank=True,
        help_text="Empty for Storage.",
    )
    number = models.CharField("room number", max_length=10)
    floor = models.PositiveSmallIntegerField(default=1)
    length_ft = models.DecimalField(
        "length (ft)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    width_ft = models.DecimalField("width (ft)", max_digits=5, decimal_places=1, null=True, blank=True)
    square_footage = models.PositiveIntegerField(
        null=True, blank=True, help_text="Calculated from length and width on the first audit."
    )
    bed_configuration = models.CharField(max_length=50, blank=True)
    bathroom_count = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=RoomStatus.choices, default=RoomStatus.ACTIVE)
    is_storage = models.BooleanField(
        default=False,
        help_text="Storage holds inventory moving in and out of service. It is not audited.",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["property", "number"], name="unique_room_number")
        ]

    def __str__(self):
        return "Storage" if self.is_storage else f"Room {self.number}"

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            from .inventory import generate_inventory

            generate_inventory(self)

    def set_dimensions(self, length_ft, width_ft):
        """Record the measured length and width; square footage is calculated."""
        self.length_ft = length_ft
        self.width_ft = width_ft
        self.square_footage = int((length_ft * width_ft).to_integral_value(ROUND_HALF_UP))
        self.save(update_fields=["length_ft", "width_ft", "square_footage"])

    # A plain method: the `property` field above shadows the builtin decorator here.
    def ac_unit(self):
        """The A/C fixture that the supply-air readings are attached to."""
        return (
            self.fixtures.filter(category=FixtureCategory.HVAC, name=AC_UNIT_NAME)
            .order_by("id")
            .first()
        )


class ItemStatus(models.TextChoices):
    IN_SERVICE = "in_service", "In service"
    RETIRED = "retired", "Retired"


class InventoryItem(models.Model):
    """Shared behaviour for the three inventory tables."""

    kind = None  # set on subclasses
    category_field = "category"

    class Meta:
        abstract = True
        ordering = ["id"]

    @property
    def category_code(self):
        return getattr(self, self.category_field)

    @property
    def base_label(self):
        return self.name or CATEGORY_LABELS[self.kind].get(self.category_code, self.category_code)

    @property
    def label(self):
        """Display name, numbered when the room has several of the same thing."""
        siblings = list(
            type(self)
            .objects.filter(
                room_id=self.room_id,
                zone=self.zone,
                name=self.name,
                **{self.category_field: self.category_code},
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        if len(siblings) > 1 and self.id in siblings:
            return f"{self.base_label} #{siblings.index(self.id) + 1}"
        return self.base_label

    def __str__(self):
        return f"{self.room} {self.get_zone_display()}: {self.base_label}"


class Furnishing(InventoryItem):
    kind = ItemKind.FURNISHING

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="furnishings")
    category = models.CharField(max_length=30, choices=FurnishingCategory.choices)
    zone = models.CharField(max_length=20, choices=Zone.choices, default=Zone.BEDROOM)
    name = models.CharField(max_length=100, blank=True)
    type_or_model = models.CharField("type or model", max_length=100, blank=True)
    quantity = models.PositiveIntegerField(
        default=1, help_text="Normally 1: each unit is its own record."
    )
    purchase_date = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    expected_life_years = models.PositiveIntegerField("expected life (years)", null=True, blank=True)
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.IN_SERVICE)
    notes = models.CharField(max_length=200, blank=True)


class Fixture(InventoryItem):
    kind = ItemKind.FIXTURE

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="fixtures")
    category = models.CharField(max_length=30, choices=FixtureCategory.choices)
    zone = models.CharField(max_length=20, choices=Zone.choices, default=Zone.BEDROOM)
    name = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, blank=True, help_text="e.g. bedroom overhead")
    make_or_model = models.CharField("make or model", max_length=100, blank=True)
    install_date = models.DateField(null=True, blank=True)
    last_serviced = models.DateField(null=True, blank=True)
    expected_life_years = models.PositiveIntegerField("expected life (years)", null=True, blank=True)
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.IN_SERVICE)
    notes = models.CharField(max_length=200, blank=True)


class BuildingElement(InventoryItem):
    kind = ItemKind.BUILDING
    category_field = "element"

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="building_elements")
    element = models.CharField(max_length=30, choices=BuildingElementType.choices)
    zone = models.CharField(max_length=20, choices=Zone.choices)
    name = models.CharField(max_length=100, blank=True)
    material_or_finish = models.CharField(
        "material or finish",
        max_length=100,
        blank=True,
        help_text="For flooring: carpet, tile or tileboard.",
    )
    last_refinished = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)


class AuditType(models.TextChoices):
    ANNUAL = "annual", "Annual"
    SPOT_CHECK = "spot_check", "Spot check"
    NEW_INVENTORY = "new_inventory", "New inventory"


class Audit(models.Model):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="audits")
    cycle_year = models.PositiveIntegerField("cycle year")
    audit_type = models.CharField(max_length=20, choices=AuditType.choices, default=AuditType.ANNUAL)
    audit_date = models.DateField(default=timezone.localdate)
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    ambient_temperature_f = models.DecimalField(
        "outside (ambient) temperature (°F)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    ac_on_at = models.DateTimeField("A/C switched on at", null=True, blank=True)
    overall_notes = models.TextField(blank=True)
    # One optional general photo per zone. Like ambient temperature, it is
    # context for the visit, so it lives on the Audit.
    bedroom_photo = models.ImageField(upload_to="zones/%Y/", null=True, blank=True)
    bathroom_photo = models.ImageField(upload_to="zones/%Y/", null=True, blank=True)

    class Meta:
        ordering = ["-audit_date", "-id"]

    def zone_photo(self, zone):
        """The general photo for a zone; only the bedroom and bathroom have one."""
        return getattr(self, f"{zone}_photo", None)

    def __str__(self):
        return f"{self.room} – {self.cycle}"

    @property
    def cycle(self):
        """Cycle label, e.g. "2026 annual"."""
        return f"{self.cycle_year} {self.get_audit_type_display().lower()}"

    @property
    def is_finished(self):
        return self.end_time is not None


class CheckType(models.TextChoices):
    CONDITION = "condition", "Condition"
    FUNCTION = "function", "Function"
    CLEANLINESS = "cleanliness", "Cleanliness"
    SECURE = "secure", "Secure"
    PRESENCE = "presence", "Presence"
    PEST = "pest", "Pest"
    NOISE = "noise", "Noise"
    SMELL = "smell", "Smell"
    MEASUREMENT = "measurement", "Measurement"


# Order in which an item's checks are shown and listed in an issue title.
CHECK_ORDER = [
    CheckType.CONDITION,
    CheckType.PRESENCE,
    CheckType.FUNCTION,
    CheckType.NOISE,
    CheckType.PEST,
    CheckType.SMELL,
    CheckType.CLEANLINESS,
    CheckType.SECURE,
    CheckType.MEASUREMENT,
]

OTHER = "other"
NOT_APPLICABLE = "n_a"

# A short result option list per check type. Every list ends with Other,
# which opens a free-text field.
RESULT_OPTIONS = {
    CheckType.CONDITION: [
        ("ok", "OK"),
        ("worn", "Worn"),
        ("damaged", "Damaged"),
        ("missing", "Missing"),
        ("not_working", "Not working"),
        ("intermittent", "Intermittent"),
        (NOT_APPLICABLE, "N/A"),
        (OTHER, "Other"),
    ],
    CheckType.FUNCTION: [
        ("working", "Working"),
        ("intermittent", "Intermittent"),
        ("not_working", "Not working"),
        (OTHER, "Other"),
    ],
    CheckType.CLEANLINESS: [
        ("clean", "Clean"),
        ("dirty", "Dirty"),
        ("stained", "Stained"),
        (OTHER, "Other"),
    ],
    CheckType.SECURE: [("secure", "Secure"), ("loose", "Loose"), (OTHER, "Other")],
    CheckType.PRESENCE: [("present", "Present"), ("missing", "Missing"), (OTHER, "Other")],
    CheckType.PEST: [("pass", "Pass"), ("fail", "Fail"), (OTHER, "Other")],
    CheckType.NOISE: [("pass", "Pass"), ("fail", "Fail"), (OTHER, "Other")],
    CheckType.SMELL: [("ok", "OK"), ("musty", "Musty"), ("smoke", "Smoke"), (OTHER, "Other")],
    CheckType.MEASUREMENT: [],
}

# Results that mean "nothing wrong". Any other answered result is a problem.
GOOD_RESULTS = {"ok", "working", "clean", "secure", "present", "pass", NOT_APPLICABLE}

RESULT_LABELS = {value: label for options in RESULT_OPTIONS.values() for value, label in options}


class ActionBucket(models.TextChoices):
    NONE = "none", "None"
    FIX_NOW = "fix_now", "Fix now"
    WORK_ORDER = "work_order", "Work order"
    CAPEX = "capex", "Capex"


# Only these buckets create an Issue. "None" stays on the Finding.
ISSUE_BUCKETS = (ActionBucket.FIX_NOW, ActionBucket.WORK_ORDER, ActionBucket.CAPEX)

AC_OUTFLOW_LABEL = "A/C outflow air"
PILLOWS_LABEL = "Pillows to replace"
NOISE_OUTSIDE_LABEL = "Peak noise outside"
NOISE_INSIDE_LABEL = "Peak noise inside (from bed)"

AUTO_CLOSE_NOTE = "Closed automatically: the audit finding was changed and is no longer a problem."


class Finding(models.Model):
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="findings")
    target_kind = models.CharField(
        max_length=20, choices=ItemKind.choices, blank=True, help_text="Blank for room-level checks."
    )
    # The target is one of the three inventory records, or, for an item that the
    # standard expects but the room does not have, the standard row. Room-level
    # checks (smell) have no target.
    furnishing = models.ForeignKey(
        Furnishing, on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    fixture = models.ForeignKey(
        Fixture, on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    building_element = models.ForeignKey(
        BuildingElement, on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    standard = models.ForeignKey(
        RoomStandard,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="findings",
        help_text="Set when the item is expected by the standard but absent from the room.",
    )
    check_type = models.CharField(max_length=20, choices=CheckType.choices)
    result = models.CharField(max_length=20, blank=True, help_text="Blank means unanswered.")
    result_other = models.CharField("other (free text)", max_length=200, blank=True)
    condition_score = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    measurement_label = models.CharField(max_length=50, blank=True)
    measured_value = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    unit = models.CharField(max_length=10, blank=True)
    measured_at = models.DateTimeField(null=True, blank=True)
    action_bucket = models.CharField(max_length=20, choices=ActionBucket.choices, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.audit}: {self.target_label} ({self.get_check_type_display()})"

    @property
    def target(self):
        return self.furnishing or self.fixture or self.building_element

    @property
    def target_label(self):
        if self.target:
            return self.target.label
        if self.standard:
            return self.standard.name
        if self.check_type == CheckType.SMELL:
            return "Room smell"
        if self.check_type == CheckType.MEASUREMENT and self.measurement_label:
            return self.measurement_label
        return "(removed item)"

    @property
    def zone(self):
        source = self.target or self.standard
        return source.zone if source else ""

    @property
    def is_answered(self):
        return bool(self.result)

    @property
    def is_problem(self):
        return self.is_answered and self.result not in GOOD_RESULTS

    @property
    def result_display(self):
        if self.result == OTHER and self.result_other:
            return f"Other: {self.result_other}"
        return RESULT_LABELS.get(self.result, self.result)

    def siblings(self):
        """This audit's findings about the same item, in check order.

        An item can have several checks (condition, works, squeak, bedbug).
        They share one action and at most one Issue.
        """
        group = [self]
        if self.check_type != CheckType.MEASUREMENT:
            for field in ("furnishing_id", "fixture_id", "building_element_id", "standard_id"):
                target_id = getattr(self, field)
                if target_id:
                    group = list(
                        Finding.objects.filter(audit_id=self.audit_id, **{field: target_id}).exclude(
                            check_type=CheckType.MEASUREMENT
                        )
                    )
                    break
        return sorted(group, key=lambda f: (CHECK_ORDER.index(f.check_type), f.id or 0))

    def issue_title(self, problems=None):
        zone = dict(Zone.choices).get(self.zone, "")
        where = f" ({zone})" if zone else ""
        group = problems or [self]
        results = ", ".join(f.result_display for f in group)
        pillows = next((f.pillows_to_replace for f in self.siblings() if f.pillows_to_replace), 0)
        if pillows:
            results += f" (replace {pillows} pillow{'s' if pillows != 1 else ''})"
        return f"{self.target_label}{where}: {results}"[:200]

    @property
    def pillows_to_replace(self):
        """The count recorded on a bedding item, or 0."""
        if self.measurement_label == PILLOWS_LABEL and self.measured_value:
            return int(self.measured_value)
        return 0

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_issue()

    def sync_issue(self):
        """Keep the item's single Issue in step: create, update or close it.

        The Issue hangs off the item's first problem finding and its title
        lists every problem found on the item.
        """
        group = self.siblings()
        problems = [f for f in group if f.is_problem]
        bucket = next((f.action_bucket for f in problems if f.action_bucket), "")
        issue = Issue.objects.filter(finding__in=[f.pk for f in group if f.pk]).first()
        if problems and bucket in ISSUE_BUCKETS:
            primary = problems[0]
            title = primary.issue_title(problems)
            if issue is None:
                Issue.objects.create(
                    finding=primary, room=self.audit.room, title=title, bucket=bucket
                )
                return
            issue.finding = primary
            issue.title = title
            issue.bucket = bucket
            # Reopen only if the app closed it; a status Bryan set is left alone.
            if issue.status == IssueStatus.DONE and issue.resolution_notes == AUTO_CLOSE_NOTE:
                issue.status = IssueStatus.OPEN
                issue.date_resolved = None
                issue.resolution_notes = ""
            issue.save()
        elif issue is not None and issue.status != IssueStatus.DONE:
            issue.status = IssueStatus.DONE
            issue.date_resolved = timezone.localdate()
            if not issue.resolution_notes:
                issue.resolution_notes = AUTO_CLOSE_NOTE
            issue.save()


class FindingPhoto(models.Model):
    """A photo of an item, taken during an audit. An item can have several."""

    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="photos")
    photo = models.ImageField(upload_to="findings/%Y/")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.photo.name


@receiver(post_delete, sender=FindingPhoto)
def remove_photo_file(sender, instance, **kwargs):
    """Delete the image file when its record goes, so files do not pile up."""
    if instance.photo:
        instance.photo.delete(save=False)


class IssueBucket(models.TextChoices):
    FIX_NOW = "fix_now", "Fix now"
    WORK_ORDER = "work_order", "Work order"
    CAPEX = "capex", "Capex"


class IssuePriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    SAFETY = "safety", "Safety"


class IssueStatus(models.TextChoices):
    OPEN = "open", "Open"
    SCHEDULED = "scheduled", "Scheduled"
    DONE = "done", "Done"
    DEFERRED = "deferred", "Deferred"


class Issue(models.Model):
    finding = models.OneToOneField(Finding, on_delete=models.CASCADE, related_name="issue")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="issues")
    title = models.CharField(max_length=200)
    bucket = models.CharField(max_length=20, choices=IssueBucket.choices)
    priority = models.CharField(
        max_length=20, choices=IssuePriority.choices, default=IssuePriority.MEDIUM
    )
    status = models.CharField(max_length=20, choices=IssueStatus.choices, default=IssueStatus.OPEN)
    cost_estimate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    date_opened = models.DateField(default=timezone.localdate)
    date_resolved = models.DateField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.room}: {self.title}"

    @property
    def item_findings(self):
        return self.finding.siblings()

    @property
    def notes_text(self):
        """Audit notes recorded on the item, joined."""
        return "; ".join(f.notes for f in self.item_findings if f.notes)

    @property
    def photos(self):
        return [p.photo for f in self.item_findings for p in f.photos.all()]
