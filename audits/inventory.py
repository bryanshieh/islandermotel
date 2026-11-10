"""Inventory generation from a room type's RoomStandard rows."""

from .models import BuildingElement, Fixture, Furnishing, ItemKind


def create_unit(room, standard):
    """Create one inventory record in `room` for one unit of `standard`."""
    common = {"room": room, "zone": standard.zone, "name": standard.name, "notes": standard.notes}
    if standard.item_kind == ItemKind.FURNISHING:
        return Furnishing.objects.create(category=standard.category, quantity=1, **common)
    if standard.item_kind == ItemKind.FIXTURE:
        return Fixture.objects.create(category=standard.category, **common)
    return BuildingElement.objects.create(element=standard.category, **common)


def has_inventory(room):
    return (
        room.furnishings.exists() or room.fixtures.exists() or room.building_elements.exists()
    )


def generate_inventory(room):
    """Copy the room type's standard into inventory, one record per unit.

    Does nothing for Storage, for a room without a type, or for a room that
    already has inventory, so it is safe to call more than once.
    Returns the number of records created.
    """
    if room.is_storage or room.room_type_id is None or has_inventory(room):
        return 0
    created = 0
    for standard in room.room_type.standards.order_by("id"):
        for _ in range(standard.expected_quantity):
            create_unit(room, standard)
            created += 1
    return created
