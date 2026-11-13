"""Seed the Islander Motel: property, room types, standards, rooms and inventory.

Safe to run more than once: existing records are left alone.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from audits.inventory import create_unit, generate_inventory
from audits.models import (
    AC_UNIT_NAME,
    ItemKind,
    Property,
    Room,
    RoomStandard,
    RoomType,
    Zone,
)

F, X, B = ItemKind.FURNISHING, ItemKind.FIXTURE, ItemKind.BUILDING
BED, BATH = Zone.BEDROOM, Zone.BATHROOM

# (zone, name, kind, category or element, quantity, notes)
# From "Default inventory per room" in docs/PRD.md, with Bryan's changes after
# the first test run: there is no entry zone (the entry door is a bedroom item
# that covers its hinges, locks and threshold), the bedroom has a mini fridge,
# the bathroom has an outlet, and the shower has two handles (hot and cold).
# Things fixed or replaced together are one row: the A/C with its casing and
# filter, the heater with its pilot, all lamps, and the bedding.
# Decor is not seeded; it is counted on the first audit.
STANDARD_ITEMS = [
    (BED, "Entry door", B, "door", 1, "Deadbolt, plus doorknob with lock; includes hinges and threshold"),
    (BED, "Bed frame", F, "bed_frame", 1, "Queen"),
    (BED, "Headboard", F, "headboard", 1, "Queen"),
    (BED, "Mattress", F, "mattress", 1, "Queen"),
    (BED, "Box spring", F, "box_spring", 1, "Queen"),
    (BED, "Table", F, "table", 1, ""),
    (BED, "Chair", F, "chair", 2, ""),
    (BED, "TV", X, "tv", 1, ""),
    (BED, "Overhead light", X, "light", 1, ""),
    (BED, "Sconces and lamps", X, "light", 1, "All sconces and lamps; add a photo of each problem"),
    (BED, "Mirror", X, "mirror", 1, ""),
    (BED, AC_UNIT_NAME, X, "hvac", 1, "Unit, casing and filter"),
    (BED, "Heater", X, "heater", 1, "Heater and pilot"),
    (BED, "Dresser", F, "dresser", 1, ""),
    (BED, "Bedding", F, "bedding", 1, "Comforter and 2 pillows"),
    (BED, "Outlet", X, "outlet", 1, "All outlets in the bedroom"),
    (BED, "Smoke detector", X, "smoke_detector", 1, ""),
    (BED, "Mini fridge", X, "mini_fridge", 1, ""),
    (BATH, "Light", X, "light", 1, ""),
    (BATH, "Mirror", X, "mirror", 1, ""),
    (BATH, "Toilet", X, "toilet", 1, ""),
    (BATH, "Sink", X, "sink", 1, ""),
    (BATH, "Sink counter", B, "counter", 1, ""),
    (BATH, "Shower", X, "shower", 1, "Shower head and two handles (hot and cold)"),
    (BATH, "Towel rack", X, "towel_rack", 1, ""),
    (BATH, "Outlet", X, "outlet", 1, "All outlets in the bathroom"),
]

# "All zones" rows: one record per zone (bedroom and bathroom).
PER_ZONE_ITEMS = [
    ("Walls", "wall", ""),
    ("Flooring", "floor", "Carpet, tile or tileboard"),
    ("Windows", "window", ""),
    ("Trim", "trim", ""),
]
for _zone in (BED, BATH):
    for _name, _element, _notes in PER_ZONE_ITEMS:
        STANDARD_ITEMS.append((_zone, _name, B, _element, 1, _notes))
# One signage row covers the whole room.
STANDARD_ITEMS.append(
    (BED, "Signage", B, "signage", 1, "Whole room, for example no smoking, do not flush tampons")
)
# Ceilings are in the PRD audit flow for the bedroom and bathroom.
for _zone in (BED, BATH):
    STANDARD_ITEMS.append((_zone, "Ceiling", B, "ceiling", 1, ""))

ROOMS_BY_TYPE = {
    "SML": ["7", "11", "12", "14", "15", "20", "21"],
    "STD": [str(n) for n in range(101, 111)] + [str(n) for n in range(201, 211)],
    "LRG": ["8", "16", "17", "18", "19"],
    "XLRG": ["9", "10"],
}
SECOND_FLOOR = {"9", "10"} | {str(n) for n in range(201, 211)}
STORAGE_NUMBER = "00"

# Room 9 is the only exception to the standard: total units per item name.
ROOM_OVERRIDES = {
    "9": {
        "Bed frame": 2,
        "Headboard": 2,
        "Mattress": 2,
        "Box spring": 2,
        "Dresser": 2,
        "Bedding": 2,  # one set per bed: 2 comforters, 4 pillows
    }
}
BED_CONFIGURATION = {"9": "2 queen"}


class Command(BaseCommand):
    help = "Seed the property, room types, room standards, 35 rooms and their inventory."

    @transaction.atomic
    def handle(self, *args, **options):
        prop, _ = Property.objects.get_or_create(
            name="Islander Motel", defaults={"unit_count": 34}
        )

        for type_name in ROOMS_BY_TYPE:
            room_type, _ = RoomType.objects.get_or_create(property=prop, name=type_name)
            if not room_type.standards.exists():
                RoomStandard.objects.bulk_create(
                    RoomStandard(
                        room_type=room_type,
                        zone=zone,
                        name=name,
                        item_kind=kind,
                        category=category,
                        expected_quantity=quantity,
                        notes=notes,
                    )
                    for zone, name, kind, category, quantity, notes in STANDARD_ITEMS
                )

        rooms_created = 0
        for type_name, numbers in ROOMS_BY_TYPE.items():
            room_type = RoomType.objects.get(property=prop, name=type_name)
            for number in numbers:
                # Creating a Room generates its inventory from the standard.
                room, created = Room.objects.get_or_create(
                    property=prop,
                    number=number,
                    defaults={
                        "room_type": room_type,
                        "floor": 2 if number in SECOND_FLOOR else 1,
                        "bed_configuration": BED_CONFIGURATION.get(number, "1 queen"),
                    },
                )
                rooms_created += created
                generate_inventory(room)  # no-op when the room already has inventory
                if created:
                    self.apply_overrides(room)

        _, created = Room.objects.get_or_create(
            property=prop,
            number=STORAGE_NUMBER,
            defaults={"is_storage": True, "room_type": None, "floor": 1, "bathroom_count": 0},
        )
        rooms_created += created

        if options["verbosity"] > 0:
            self.stdout.write(self.style.SUCCESS(
                f"Seed complete: {Room.objects.count()} rooms ({rooms_created} new), "
                f"{RoomType.objects.count()} room types, "
                f"{RoomStandard.objects.count()} standard rows."
            ))

    def apply_overrides(self, room):
        for name, total in ROOM_OVERRIDES.get(room.number, {}).items():
            standard = room.room_type.standards.get(name=name)
            have = standard.inventory_queryset(room).count()
            for _ in range(total - have):
                create_unit(room, standard)
