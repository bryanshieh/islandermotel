from django.contrib import admin, messages

from .inventory import generate_inventory
from .models import (
    Audit,
    BuildingElement,
    Finding,
    Fixture,
    Furnishing,
    Issue,
    Property,
    Room,
    RoomStandard,
    RoomType,
)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "state", "unit_count"]


class RoomStandardInline(admin.TabularInline):
    model = RoomStandard
    extra = 0


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "property", "default_square_footage"]
    inlines = [RoomStandardInline]


@admin.register(RoomStandard)
class RoomStandardAdmin(admin.ModelAdmin):
    list_display = ["room_type", "zone", "name", "item_kind", "category", "expected_quantity"]
    list_filter = ["room_type", "zone", "item_kind"]


class FurnishingInline(admin.TabularInline):
    model = Furnishing
    extra = 0
    fields = ["category", "zone", "name", "type_or_model", "status", "notes"]


class FixtureInline(admin.TabularInline):
    model = Fixture
    extra = 0
    fields = ["category", "zone", "name", "location", "make_or_model", "status", "notes"]


class BuildingElementInline(admin.TabularInline):
    model = BuildingElement
    extra = 0
    fields = ["element", "zone", "name", "material_or_finish", "notes"]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["number", "room_type", "floor", "length_ft", "width_ft", "square_footage", "bed_configuration", "status", "is_storage"]
    list_filter = ["room_type", "floor", "status", "is_storage"]
    search_fields = ["number"]
    inlines = [FurnishingInline, FixtureInline, BuildingElementInline]
    actions = ["generate_inventory_action"]

    @admin.action(description="Generate inventory from the room type standard (empty rooms only)")
    def generate_inventory_action(self, request, queryset):
        created = sum(generate_inventory(room) for room in queryset)
        self.message_user(request, f"Created {created} inventory records.", messages.SUCCESS)


@admin.register(Furnishing)
class FurnishingAdmin(admin.ModelAdmin):
    list_display = ["room", "zone", "name", "category", "type_or_model", "status"]
    list_filter = ["category", "zone", "status", "room__room_type"]
    search_fields = ["room__number", "name"]


@admin.register(Fixture)
class FixtureAdmin(admin.ModelAdmin):
    list_display = ["room", "zone", "name", "category", "location", "status"]
    list_filter = ["category", "zone", "status", "room__room_type"]
    search_fields = ["room__number", "name"]


@admin.register(BuildingElement)
class BuildingElementAdmin(admin.ModelAdmin):
    list_display = ["room", "zone", "name", "element", "material_or_finish"]
    list_filter = ["element", "zone", "room__room_type"]
    search_fields = ["room__number", "name"]


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["room", "cycle_year", "audit_type", "audit_date", "auditor", "ac_on_at", "end_time"]
    list_filter = ["cycle_year", "audit_type", "room__room_type"]
    search_fields = ["room__number"]


@admin.register(Finding)
class FindingAdmin(admin.ModelAdmin):
    list_display = ["audit", "target_label", "check_type", "result", "action_bucket", "measured_value"]
    list_filter = ["check_type", "result", "action_bucket", "audit__cycle_year"]
    search_fields = ["audit__room__number"]
    raw_id_fields = ["audit", "furnishing", "fixture", "building_element", "standard"]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["room", "title", "bucket", "priority", "status", "cost_estimate", "date_opened", "date_resolved"]
    list_filter = ["bucket", "status", "priority", "room__room_type"]
    search_fields = ["room__number", "title"]
    raw_id_fields = ["finding"]
