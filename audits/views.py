import csv
from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.static import serve as static_serve

from . import checklist
from .ac import ac_result, reading, set_outflow
from .forms import IssueForm, NewAuditForm, NoiseForm, OtherItemForm, StartForm, WrapUpForm
from .models import (
    AC_OUTFLOW_LABEL,
    FLOORING_TYPES,
    NOT_APPLICABLE,
    OTHER,
    RESULT_OPTIONS,
    ActionBucket,
    Audit,
    BuildingElement,
    BuildingElementType,
    Finding,
    Furnishing,
    FurnishingCategory,
    Issue,
    IssueBucket,
    IssueStatus,
    Room,
    RoomType,
    Zone,
    room_sort_key,
)
from .noise import noise_result, set_noise
from .photos import NotAPhoto, shrink_photo

STEPS = [
    ("start", "Start"),
    ("bedroom", "Bedroom"),
    ("bathroom", "Bathroom"),
    ("other", "Other"),
    ("wrapup", "Wrap-up"),
]
STEP_SLUGS = [slug for slug, _ in STEPS]
PHOTO_ERROR = "That file is not a photo the app can read. Try a JPEG or PNG."


def next_step(step):
    index = STEP_SLUGS.index(step)
    return STEP_SLUGS[min(index + 1, len(STEP_SLUGS) - 1)]


def step_nav(audit, current):
    counts = checklist.zone_counts(audit)
    nav = []
    for slug, label in STEPS:
        total, unanswered = counts.get(slug, (None, None))
        nav.append(
            {
                "slug": slug,
                "label": label,
                "current": slug == current,
                "total": total,
                "unanswered": unanswered,
            }
        )
    return nav


def local_input_value(moment):
    """A datetime as the text a datetime-local input expects, in Pacific time."""
    return timezone.localtime(moment).strftime("%Y-%m-%dT%H:%M") if moment else ""


@login_required
def home(request):
    form = NewAuditForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        room = get_object_or_404(Room, pk=form.cleaned_data["room"], is_storage=False)
        year = form.cleaned_data["cycle_year"]
        audit_type = form.cleaned_data["audit_type"]
        # Resume an unfinished audit for the same room and cycle instead of
        # starting a duplicate.
        audit = Audit.objects.filter(
            room=room, cycle_year=year, audit_type=audit_type, end_time__isnull=True
        ).first()
        if audit is None:
            audit = Audit.objects.create(
                room=room, cycle_year=year, audit_type=audit_type, auditor=request.user
            )
        else:
            messages.info(request, f"Resumed the unfinished {audit.cycle} audit of {room}.")
        return redirect("audit_step", pk=audit.pk, step="start")

    audits = Audit.objects.select_related("room", "room__room_type")
    return render(request, "audits/home.html", {"form": form, "audits": audits})


@login_required
def audit_step(request, pk, step):
    audit = get_object_or_404(Audit.objects.select_related("room", "room__room_type"), pk=pk)
    if step not in STEP_SLUGS:
        raise Http404
    if step == "start":
        return start_step(request, audit)
    if step == "wrapup":
        return wrapup_step(request, audit)
    return zone_step(request, audit, step)


def start_step(request, audit):
    room = audit.room
    first_audit = not room.audits.filter(pk__lt=audit.pk).exists()
    ask_dimensions = room.square_footage is None or first_audit
    form = StartForm(
        request.POST or None,
        initial={
            "ambient_temperature_f": audit.ambient_temperature_f,
            "room_length_ft": room.length_ft,
            "room_width_ft": room.width_ft,
            "noise_outside_db": noise_result(audit).outside,
            "ac_on_time": audit.ac_on_at,
        },
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        audit.ambient_temperature_f = data["ambient_temperature_f"]
        audit.ac_on_at = data["ac_on_time"]
        audit.save()
        if ask_dimensions and data["room_length_ft"] and data["room_width_ft"]:
            room.set_dimensions(data["room_length_ft"], data["room_width_ft"])
        set_noise(audit, "outside", data["noise_outside_db"])
        if request.POST.get("action") == "continue":
            return redirect("audit_step", pk=audit.pk, step=next_step("start"))
        messages.success(request, "Saved.")
        return redirect("audit_step", pk=audit.pk, step="start")
    return render(
        request,
        "audits/step_start.html",
        {
            "audit": audit,
            "room": room,
            "form": form,
            "ask_dimensions": ask_dimensions,
            "ac_on_value": request.POST.get("ac_on_time", "")
            if form.is_bound
            else local_input_value(audit.ac_on_at),
            "nav": step_nav(audit, "start"),
            "entry": checklist.smell_entry(audit),
            "buckets": ActionBucket.choices,
        },
    )


@login_required
@require_POST
def ac_on(request, pk):
    """Record that the A/C was switched on just now (the server's clock)."""
    audit = get_object_or_404(Audit, pk=pk)
    audit.ac_on_at = timezone.now()
    audit.save(update_fields=["ac_on_at"])
    return render(
        request,
        "audits/_ac_on.html",
        {"audit": audit, "ac_on_value": local_input_value(audit.ac_on_at)},
    )


def zone_context(audit, zone):
    return {
        "audit": audit,
        "zone": zone,
        "entries": checklist.build_zone(audit, zone),
        "buckets": ActionBucket.choices,
        "flooring_types": FLOORING_TYPES,
        "other_form": OtherItemForm() if zone == Zone.OTHER else None,
    }


def zone_step(request, audit, step):
    zone = Zone(step)
    has_photo = zone in (Zone.BEDROOM, Zone.BATHROOM)
    return render(
        request,
        "audits/step_zone.html",
        {
            **zone_context(audit, zone),
            "room": audit.room,
            "nav": step_nav(audit, step),
            "next_step": next_step(step),
            "next_label": dict(STEPS)[next_step(step)],
            "has_zone_photo": has_photo,
            "zone_photo": audit.zone_photo(zone) if has_photo else None,
            "noise_inside": noise_result(audit).inside if zone == Zone.BEDROOM else None,
            "show_noise": zone == Zone.BEDROOM,
        },
    )


@login_required
@require_POST
def noise_inside(request, pk):
    """Autosave the peak dB reading taken inside the bedroom, from the bed."""
    audit = get_object_or_404(Audit, pk=pk)
    form = NoiseForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Enter a number between 0 and 200")
    set_noise(audit, "inside", form.cleaned_data["value"])
    return HttpResponse(status=204)


@login_required
@require_POST
def zone_photo(request, pk, zone):
    """Add, replace or remove the optional general photo of a zone."""
    audit = get_object_or_404(Audit, pk=pk)
    if zone not in (Zone.BEDROOM, Zone.BATHROOM):
        raise Http404
    zone = Zone(zone)
    field = f"{zone}_photo"
    current = getattr(audit, field)
    photo_error = ""
    if request.POST.get("remove_photo") and current:
        current.delete(save=False)
    if "photo" in request.FILES:
        try:
            photo = shrink_photo(request.FILES["photo"])
        except NotAPhoto:
            photo_error = PHOTO_ERROR
        else:
            if current:
                current.delete(save=False)  # replace, do not pile up files
            setattr(audit, field, photo)
    audit.save()
    return render(
        request,
        "audits/_zone_photo.html",
        {
            "audit": audit,
            "zone": zone,
            "zone_photo": audit.zone_photo(zone),
            "photo_error": photo_error,
        },
    )


def wrapup_step(request, audit):
    outflow = reading(audit, AC_OUTFLOW_LABEL)
    form = WrapUpForm(
        request.POST or None,
        initial={
            "ac_outflow_value": outflow.measured_value if outflow else None,
            "ac_outflow_time": outflow.measured_at if outflow else None,
            "overall_notes": audit.overall_notes,
        },
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        # Time of the reading: as entered, else as already saved, else now.
        measured_at = (
            data["ac_outflow_time"]
            or (outflow.measured_at if outflow else None)
            or timezone.now()
        )
        set_outflow(audit, data["ac_outflow_value"], measured_at)
        audit.overall_notes = data["overall_notes"]
        finishing = request.POST.get("action") == "finish"
        if finishing and audit.end_time is None:
            audit.end_time = timezone.now()
        audit.save()
        if finishing:
            messages.success(request, f"Audit of {audit.room} saved and finished.")
            return redirect("home")
        messages.success(request, "Saved.")
        return redirect("audit_step", pk=audit.pk, step="wrapup")

    nav = step_nav(audit, "wrapup")
    issues = {f.issue.pk: f.issue for f in audit.findings.all() if hasattr(f, "issue")}
    return render(
        request,
        "audits/step_wrapup.html",
        {
            "audit": audit,
            "room": audit.room,
            "form": form,
            "nav": nav,
            "ac": ac_result(audit),
            "noise": noise_result(audit),
            "unanswered_total": sum(step["unanswered"] or 0 for step in nav),
            "issues": list(issues.values()),
        },
    )


@login_required
@require_POST
def item_update(request, pk):
    """Autosave one tap or field change on one item; returns the item's HTML.

    `item` names the item. A result (or an Other description) also needs
    `key`, the check it answers. The action, note and photo belong to the
    item as a whole.
    """
    audit = get_object_or_404(Audit.objects.select_related("room", "room__room_type"), pk=pk)
    item_key = request.POST.get("item", "")
    entry = checklist.find_entry(audit, item_key)
    if entry is None:
        raise Http404
    post = request.POST

    if "result" in post or "result_other" in post:
        row = entry.row(post.get("key", ""))
        if row is None:
            raise Http404
        finding = row.get_or_build_finding(audit)
        if "result" in post:
            result = post["result"]
            if result and result not in dict(RESULT_OPTIONS[row.check_type]):
                return HttpResponseBadRequest("Unknown result")
            finding.result = result
            if result != OTHER:
                finding.result_other = ""
            if finding.is_problem:
                # One action per item: a new problem takes the item's action.
                finding.action_bucket = finding.action_bucket or entry.action
            else:
                finding.action_bucket = ""
        if "result_other" in post and finding.result == OTHER:
            finding.result_other = post["result_other"].strip()[:200]
        finding.save()
        if row is entry.anchor and finding.result == NOT_APPLICABLE:
            # Nothing to do on an item that is not applicable: clear its other
            # checks. The note and photo stay.
            for other in entry.checks[1:]:
                if other.finding and (other.finding.result or other.finding.action_bucket):
                    other.finding.result = ""
                    other.finding.result_other = ""
                    other.finding.action_bucket = ""
                    other.finding.save()

    if "action_bucket" in post:
        bucket = post["action_bucket"]
        if bucket not in ActionBucket.values:
            return HttpResponseBadRequest("Unknown action")
        for finding in entry.problems:
            finding.action_bucket = bucket
            finding.save()

    photo_error = ""
    wants_anchor = (
        ("notes" in post and post["notes"].strip() != entry.notes)
        or "photo" in request.FILES
        or post.get("remove_photo")
    )
    if wants_anchor:
        anchor = entry.anchor.get_or_build_finding(audit)
        if anchor.pk:
            anchor.refresh_from_db()  # pick up a result saved above
        if "notes" in post:
            anchor.notes = post["notes"].strip()
        if post.get("remove_photo") and anchor.photo:
            anchor.photo.delete(save=False)
        if "photo" in request.FILES:
            try:
                photo = shrink_photo(request.FILES["photo"])
            except NotAPhoto:
                photo_error = PHOTO_ERROR
            else:
                if anchor.photo:
                    anchor.photo.delete(save=False)  # replace, do not pile up files
                anchor.photo = photo
        anchor.save()

    return render(
        request,
        "audits/_item.html",
        {
            "audit": audit,
            "entry": checklist.find_entry(audit, item_key),
            "buckets": ActionBucket.choices,
            "flooring_types": FLOORING_TYPES,
            "photo_error": photo_error,
        },
    )


def other_items(request, audit):
    return render(request, "audits/_zone_items.html", zone_context(audit, Zone.OTHER))


@login_required
@require_POST
def add_other_item(request, pk):
    """Add an item that is not on the standard list (decor and the like)."""
    audit = get_object_or_404(Audit, pk=pk)
    form = OtherItemForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Name the item to add it")
    Furnishing.objects.create(
        room=audit.room,
        category=FurnishingCategory.OTHER,
        zone=Zone.OTHER,
        name=form.cleaned_data["name"],
    )
    return other_items(request, audit)


@login_required
@require_POST
def delete_other_item(request, pk, item_pk):
    """Delete an item added during an audit, with this audit's findings on it."""
    audit = get_object_or_404(Audit, pk=pk)
    item = get_object_or_404(Furnishing, pk=item_pk, room=audit.room, zone=Zone.OTHER)
    Finding.objects.filter(audit=audit, furnishing=item).delete()
    item.delete()
    return other_items(request, audit)


@login_required
@require_POST
def set_material(request, pk, item_pk):
    """One-tap flooring type; saved on the flooring record itself."""
    audit = get_object_or_404(Audit, pk=pk)
    item = get_object_or_404(
        BuildingElement, pk=item_pk, room=audit.room, element=BuildingElementType.FLOOR
    )
    material = request.POST.get("material", "")
    if material and material not in FLOORING_TYPES:
        return HttpResponseBadRequest("Unknown flooring type")
    item.material_or_finish = material
    item.save(update_fields=["material_or_finish"])
    return render(
        request,
        "audits/_material.html",
        {"audit": audit, "item": item, "flooring_types": FLOORING_TYPES},
    )


@login_required
def media(request, path):
    """Serve a finding photo from the media folder to a logged-in user."""
    return static_serve(request, path, document_root=settings.MEDIA_ROOT)


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filtered_issues(params):
    """Issues matching the list filters, sorted by room number."""
    issues = Issue.objects.filter(room__is_storage=False).select_related(
        "room", "room__room_type", "finding", "finding__audit"
    )
    selected = {
        "bucket": params.get("bucket", "") if params.get("bucket") in IssueBucket.values else "",
        "status": params.get("status", "") if params.get("status") in IssueStatus.values else "",
        "room": to_int(params.get("room")),
        "room_type": to_int(params.get("room_type")),
        "cycle": to_int(params.get("cycle")),
    }
    if selected["bucket"]:
        issues = issues.filter(bucket=selected["bucket"])
    if selected["status"]:
        issues = issues.filter(status=selected["status"])
    if selected["room"]:
        issues = issues.filter(room_id=selected["room"])
    if selected["room_type"]:
        issues = issues.filter(room__room_type_id=selected["room_type"])
    if selected["cycle"]:
        issues = issues.filter(finding__audit__cycle_year=selected["cycle"])
    issues = sorted(issues, key=lambda issue: (room_sort_key(issue.room.number), issue.id))
    return issues, selected


def cycle_years():
    return sorted(set(Audit.objects.values_list("cycle_year", flat=True)), reverse=True)


@login_required
def issue_list(request):
    issues, selected = filtered_issues(request.GET)
    rooms = sorted(
        Room.objects.filter(is_storage=False), key=lambda room: room_sort_key(room.number)
    )
    return render(
        request,
        "audits/issue_list.html",
        {
            "issues": issues,
            "selected": selected,
            "buckets": IssueBucket.choices,
            "statuses": IssueStatus.choices,
            "rooms": rooms,
            "room_types": RoomType.objects.all(),
            "cycles": cycle_years(),
            "query": request.GET.urlencode(),
        },
    )


@login_required
def issue_export(request):
    """CSV of the current filtered view."""
    issues, _ = filtered_issues(request.GET)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="islander-issues-{timezone.localdate():%Y-%m-%d}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "Room",
            "Room type",
            "Item",
            "Bucket",
            "Priority",
            "Status",
            "Cost estimate",
            "Cycle",
            "Date opened",
            "Date resolved",
            "Resolution notes",
            "Finding notes",
        ]
    )
    for issue in issues:
        writer.writerow(
            [
                issue.room.number,
                issue.room.room_type or "",
                issue.title,
                issue.get_bucket_display(),
                issue.get_priority_display(),
                issue.get_status_display(),
                issue.cost_estimate if issue.cost_estimate is not None else "",
                issue.finding.audit.cycle,
                issue.date_opened.isoformat(),
                issue.date_resolved.isoformat() if issue.date_resolved else "",
                issue.resolution_notes,
                issue.notes_text,
            ]
        )
    return response


@login_required
@require_POST
def issue_status(request, pk):
    """Change an issue's status from the list; returns the table row."""
    issue = get_object_or_404(Issue, pk=pk)
    status = request.POST.get("status")
    if status not in IssueStatus.values:
        return HttpResponseBadRequest("Unknown status")
    issue.status = status
    if status == IssueStatus.DONE and issue.date_resolved is None:
        issue.date_resolved = timezone.localdate()
    issue.save()
    return render(
        request,
        "audits/_issue_row.html",
        {"issue": issue, "statuses": IssueStatus.choices, "query": request.POST.get("query", "")},
    )


@login_required
def issue_edit(request, pk):
    issue = get_object_or_404(
        Issue.objects.select_related("room", "finding", "finding__audit"), pk=pk
    )
    back = reverse("issue_list")
    query = request.GET.get("back", "")
    if query:
        back = f"{back}?{query}"
    form = IssueForm(request.POST or None, instance=issue)
    if request.method == "POST" and form.is_valid():
        issue = form.save(commit=False)
        if issue.status == IssueStatus.DONE and issue.date_resolved is None:
            issue.date_resolved = timezone.localdate()
        issue.save()
        messages.success(request, f"Saved issue: {issue.title}")
        return redirect(back)
    return render(request, "audits/issue_edit.html", {"issue": issue, "form": form, "back": back})


@login_required
def dashboard(request):
    """Totals for one audit cycle. Storage is excluded from every count."""
    years = cycle_years()
    year = to_int(request.GET.get("cycle"))
    if year not in years:
        year = years[0] if years else None

    issues = Issue.objects.filter(room__is_storage=False, finding__audit__cycle_year=year)
    by_bucket = Counter(issues.values_list("bucket", flat=True))
    by_type = Counter(issues.values_list("room__room_type_id", flat=True))
    bucket_rows = [(value, label, by_bucket[value]) for value, label in IssueBucket.choices]
    type_rows = [(rt, by_type[rt.id]) for rt in RoomType.objects.all()]

    # A/C readings per room, from each room's most recent audit in the cycle.
    latest = {}
    audits = (
        Audit.objects.filter(cycle_year=year, room__is_storage=False)
        .select_related("room", "room__room_type")
        .prefetch_related("findings")
        .order_by("audit_date", "id")
    )
    for audit in audits:
        latest[audit.room_id] = audit
    ac_rows = sorted(
        ({"room": audit.room, "audit": audit, "ac": ac_result(audit)} for audit in latest.values()),
        key=lambda row: room_sort_key(row["room"].number),
    )

    return render(
        request,
        "audits/dashboard.html",
        {
            "years": years,
            "year": year,
            "issue_total": sum(by_bucket.values()),
            "bucket_rows": bucket_rows,
            "type_rows": type_rows,
            "ac_rows": ac_rows,
        },
    )
