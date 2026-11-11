from django import forms
from django.utils import timezone

from .models import AuditType, Issue, Room, room_sort_key

DATETIME_LOCAL = "%Y-%m-%dT%H:%M"


def temperature_field(label):
    return forms.DecimalField(
        label=label,
        required=False,
        max_digits=5,
        decimal_places=1,
        min_value=-50,
        max_value=200,
        widget=forms.NumberInput(attrs={"step": "0.1", "inputmode": "decimal"}),
    )


def reading_time_field(label):
    return forms.DateTimeField(
        label=label,
        required=False,
        input_formats=[DATETIME_LOCAL, "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(format=DATETIME_LOCAL, attrs={"type": "datetime-local"}),
    )


class NewAuditForm(forms.Form):
    room = forms.ChoiceField()
    audit_type = forms.ChoiceField(choices=AuditType.choices, initial=AuditType.ANNUAL)
    cycle_year = forms.IntegerField(min_value=2000, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = sorted(
            Room.objects.filter(is_storage=False).select_related("room_type"),
            key=lambda room: room_sort_key(room.number),
        )
        self.fields["room"].choices = [("", "Pick a room")] + [
            (room.id, f"{room.number} ({room.room_type})") for room in rooms
        ]
        self.fields["cycle_year"].initial = timezone.localdate().year


class StartForm(forms.Form):
    ambient_temperature_f = temperature_field("Ambient temperature (°F)")
    square_footage = forms.IntegerField(
        label="Room square footage", required=False, min_value=1, max_value=5000
    )
    ac_start_value = temperature_field("A/C supply air, first reading (°F)")
    ac_start_time = reading_time_field("Time of first reading")


class WrapUpForm(forms.Form):
    ac_end_value = temperature_field("A/C supply air, second reading (°F)")
    ac_end_time = reading_time_field("Time of second reading")
    overall_rating = forms.TypedChoiceField(
        label="Overall rating",
        required=False,
        coerce=int,
        empty_value=None,
        choices=[(1, "1"), (2, "2"), (3, "3"), (4, "4")],
        widget=forms.RadioSelect,
    )
    overall_notes = forms.CharField(
        label="Overall notes", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )


class DecorForm(forms.Form):
    description = forms.CharField(
        max_length=100, widget=forms.TextInput(attrs={"placeholder": "e.g. Framed beach print"})
    )


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ["status", "priority", "cost_estimate", "date_resolved", "resolution_notes"]
        widgets = {
            "date_resolved": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "resolution_notes": forms.Textarea(attrs={"rows": 3}),
        }

