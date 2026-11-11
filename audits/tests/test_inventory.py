from django.core.management import call_command
from django.test import TestCase

from audits.inventory import generate_inventory
from audits.models import (
    BuildingElement,
    Fixture,
    Furnishing,
    ItemKind,
    Property,
    Room,
    RoomStandard,
    RoomType,
    Zone,
)


class GenerateInventoryTests(TestCase):
    def setUp(self):
        self.prop = Property.objects.create(name="Test Motel")
        self.room_type = RoomType.objects.create(property=self.prop, name="STD")

        def standard(kind, category, zone, name, quantity=1):
            RoomStandard.objects.create(
                room_type=self.room_type,
                item_kind=kind,
                category=category,
                zone=zone,
                name=name,
                expected_quantity=quantity,
            )

        standard(ItemKind.FURNISHING, "chair", Zone.BEDROOM, "Chair", 2)
        standard(ItemKind.FIXTURE, "tv", Zone.BEDROOM, "TV")
        for zone in (Zone.BEDROOM, Zone.BATHROOM):
            standard(ItemKind.BUILDING, "wall", zone, "Walls")

    def test_creating_a_room_generates_one_record_per_unit(self):
        room = Room.objects.create(property=self.prop, room_type=self.room_type, number="101")
        chairs = room.furnishings.filter(category="chair")
        self.assertEqual(chairs.count(), 2)  # two chairs make two records
        self.assertTrue(all(chair.quantity == 1 for chair in chairs))
        self.assertEqual(room.fixtures.filter(category="tv").count(), 1)

    def test_per_zone_elements_get_one_record_per_zone(self):
        room = Room.objects.create(property=self.prop, room_type=self.room_type, number="101")
        walls = room.building_elements.filter(element="wall")
        self.assertEqual(sorted(walls.values_list("zone", flat=True)), ["bathroom", "bedroom"])

    def test_generation_is_not_repeated(self):
        room = Room.objects.create(property=self.prop, room_type=self.room_type, number="101")
        self.assertEqual(generate_inventory(room), 0)
        room.save()
        self.assertEqual(room.furnishings.count(), 2)

    def test_storage_gets_no_inventory(self):
        storage = Room.objects.create(
            property=self.prop, room_type=self.room_type, number="00", is_storage=True
        )
        self.assertEqual(generate_inventory(storage), 0)
        self.assertFalse(storage.furnishings.exists())
        self.assertFalse(storage.fixtures.exists())
        self.assertFalse(storage.building_elements.exists())

    def test_duplicate_units_are_numbered_in_labels(self):
        room = Room.objects.create(property=self.prop, room_type=self.room_type, number="101")
        labels = [chair.label for chair in room.furnishings.filter(category="chair")]
        self.assertEqual(labels, ["Chair #1", "Chair #2"])
        self.assertEqual(room.fixtures.get(category="tv").label, "TV")


class SeedCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)

    def test_rooms_and_types(self):
        self.assertEqual(Room.objects.count(), 35)
        self.assertEqual(Room.objects.filter(is_storage=False).count(), 34)
        self.assertEqual(
            sorted(RoomType.objects.values_list("name", flat=True)),
            ["LRG", "SML", "STD", "XLRG"],
        )
        counts = {t.name: t.rooms.count() for t in RoomType.objects.all()}
        self.assertEqual(counts, {"SML": 7, "STD": 20, "LRG": 5, "XLRG": 2})

    def test_storage_room(self):
        storage = Room.objects.get(number="00")
        self.assertTrue(storage.is_storage)
        self.assertIsNone(storage.room_type)
        self.assertEqual(Furnishing.objects.filter(room=storage).count(), 0)
        self.assertEqual(Fixture.objects.filter(room=storage).count(), 0)
        self.assertEqual(BuildingElement.objects.filter(room=storage).count(), 0)

    def test_floors(self):
        second = set(Room.objects.filter(floor=2).values_list("number", flat=True))
        self.assertEqual(second, {"9", "10"} | {str(n) for n in range(201, 211)})
        self.assertEqual(Room.objects.filter(floor=1).count(), 23)

    def test_standard_room_inventory(self):
        room = Room.objects.get(number="101")
        self.assertEqual(room.furnishings.count(), 11)
        self.assertEqual(room.fixtures.count(), 23)
        self.assertEqual(room.building_elements.count(), 14)
        self.assertEqual(room.furnishings.filter(category="chair").count(), 2)
        self.assertEqual(room.furnishings.filter(category="pillow").count(), 2)
        self.assertEqual(room.fixtures.filter(name="Sconce or lamp").count(), 2)
        self.assertEqual(room.fixtures.filter(category="outlet", zone="bedroom").count(), 2)
        self.assertEqual(room.fixtures.filter(category="outlet", zone="bathroom").count(), 1)
        self.assertEqual(room.fixtures.filter(category="mirror", zone="bathroom").count(), 1)
        self.assertEqual(room.fixtures.filter(category="mini_fridge", zone="bedroom").count(), 1)
        self.assertEqual(room.fixtures.filter(category="shower_handle").count(), 2)
        self.assertEqual(room.fixtures.get(category="shower").notes, "Shower head")
        self.assertFalse(room.furnishings.filter(category="decor").exists())
        self.assertIsNone(room.square_footage)
        for element in ("wall", "floor", "window", "trim"):
            self.assertEqual(
                sorted(room.building_elements.filter(element=element).values_list("zone", flat=True)),
                ["bathroom", "bedroom"],
            )
        self.assertIsNotNone(room.ac_unit())

    def test_there_is_no_entry_zone(self):
        room = Room.objects.get(number="101")
        self.assertEqual(room.building_elements.get(element="door").zone, "bedroom")
        self.assertFalse(room.building_elements.filter(element__in=["hinge", "threshold"]).exists())
        self.assertEqual(
            sorted(room.building_elements.filter(element="signage").values_list("zone", flat=True)),
            ["bathroom", "bedroom"],
        )
        for model in (Furnishing, Fixture, BuildingElement, RoomStandard):
            self.assertFalse(model.objects.filter(zone="entry").exists(), model)

    def test_every_guest_room_matches_the_standard_except_room_9(self):
        for room in Room.objects.filter(is_storage=False).exclude(number="9"):
            self.assertEqual(room.furnishings.count(), 11, room)
            self.assertEqual(room.fixtures.count(), 23, room)
            self.assertEqual(room.building_elements.count(), 14, room)

    def test_room_9_exception(self):
        room = Room.objects.get(number="9")
        for category in ("bed_frame", "headboard", "mattress", "box_spring", "dresser"):
            self.assertEqual(room.furnishings.filter(category=category).count(), 2, category)
        self.assertEqual(room.furnishings.filter(category="pillow").count(), 4)
        self.assertEqual(room.furnishings.filter(category="chair").count(), 2)
        self.assertEqual(room.furnishings.count(), 18)
        self.assertEqual(room.fixtures.count(), 23)
        # Room 10 is also XLRG but follows the standard.
        self.assertEqual(Room.objects.get(number="10").furnishings.filter(category="mattress").count(), 1)

    def test_seed_is_idempotent(self):
        before = (Room.objects.count(), Furnishing.objects.count(), Fixture.objects.count(),
                  BuildingElement.objects.count(), RoomStandard.objects.count())
        call_command("seed_motel", verbosity=0)
        after = (Room.objects.count(), Furnishing.objects.count(), Fixture.objects.count(),
                 BuildingElement.objects.count(), RoomStandard.objects.count())
        self.assertEqual(before, after)
