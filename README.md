# Islander Motel room audit app (v1)

An internal web app that records a yearly condition audit of the Islander
Motel's 34 guest rooms and turns the findings into a prioritized fix list.
The product spec is [docs/PRD.md](docs/PRD.md). This build covers PRD phases
0 to 4: setup, data model, audit flow, issues and dashboard, plus the changes
Bryan asked for after the first test run (listed under "Changes from the PRD").

Stack: Django 5.2, SQLite, Django admin and built-in login, server-rendered
templates with HTMX, and Pico CSS. HTMX and Pico load from a CDN, so the
browser needs internet access. There is no JavaScript build step.

## Run it locally

You need Python 3.10 or newer. From the repository folder:

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate             # create the SQLite database
python manage.py seed_motel          # 35 rooms, 4 room types, standards, inventory
python manage.py createsuperuser     # the one login for the app
python manage.py runserver
```

Then open http://127.0.0.1:8000/ and log in.

`seed_motel` is safe to run again: it only adds what is missing.

To run the automated tests:

```bash
python manage.py test
```

## Using it

- **Audits** (home page): pick a room, audit type and cycle year, then walk
  through Start, Bedroom, Bathroom and Wrap-up. Every tap on a result
  button is saved straight away, so you can leave at any point and resume from
  the saved audits list. Unanswered items stay marked "Unanswered".
- **Issues**: one row per issue, with filters and "Export this view to CSV".
  Change status in the list, or use Edit for priority, cost estimate, date
  resolved and resolution notes.
- **Dashboard**: issue counts by bucket and room type, and A/C results per
  room, for the cycle year you select (defaults to the latest).
- **Admin** (`/admin/`): rooms, room types, room standards and inventory
  corrections.

## Resetting the test database

The seed only fills an empty database; it does not change rooms that already
exist. After pulling a version that changes the default inventory, start
again from a clean database (this deletes all audits, issues and photos):

```bash
rm -rf db.sqlite3 media
python manage.py migrate
python manage.py seed_motel
python manage.py createsuperuser
```

## Backing up

All data lives in two places in the repository folder, and neither is in Git:

- `db.sqlite3`: the database (rooms, audits, findings, issues).
- `media/`: the photos attached to findings.

Stop the server, then copy both to another location (an external drive or a
cloud folder) from time to time, and always before upgrading the app:

```bash
cp db.sqlite3 ~/Backups/islander-$(date +%F).sqlite3
cp -R media ~/Backups/islander-media-$(date +%F)
```

To restore, stop the server and copy both back into place. Keep the two
together: the database stores the file names of the photos.

## Changes from the PRD

Asked for by Bryan after the first test run. Where these differ from
`docs/PRD.md`, the app follows this list; the PRD itself has not been edited.

- **No entry zone.** The audit steps are Start, Bedroom, Bathroom, Wrap-up.
  "Entry door" is a bedroom item and covers its hinges, locks and threshold,
  which are no longer separate items. The entry's own walls, flooring, windows,
  trim and signage are gone; the bedroom and bathroom each keep one of each.
- **Smell check on Start.** A room-level check with OK, Musty, Smoke, Other.
  A problem smell takes an action and can open an Issue ("Room smell: Musty").
- **N/A** is a condition result. It counts as answered and is not a problem.
- **Every result has a free-text field**, shown as soon as a result is tapped.
  For Other it is the description; for every other result it is the note.
- **Actions are None, Fix now, Work order, Capex.** Monitor is removed.
- **Flooring type** (Carpet, Tile, Tileboard) is a one-tap choice on each
  flooring item and is saved on the flooring record, not on the audit.
- **Inventory:** the bedroom has a mini fridge; the bathroom has an outlet as
  well as its mirror; the shower has a shower head and two handles (hot and
  cold) instead of two nozzles.
- **Decor pieces can be deleted** from the bedroom step, which also removes
  that audit's answers (and any issue) for the piece. Other items are still
  added, corrected or retired in Admin.

Each guest room now starts with 48 inventory records (55 in room 9).

## Assumptions

Where the PRD left something open, the most conservative reading was chosen.
Points confirmed with Bryan are marked as such.

**Checklist**

1. *(Confirmed)* Every inventory item gets one condition check (OK, worn,
   damaged, missing, not working, N/A, Other). Fixtures that can work or not also
   get a function check (working, intermittent, not working, Other).
2. The function check applies to the A/C unit, heater, heater pilot, TV,
   lights, outlets, sink, shower, shower handles, toilet, smoke detector and
   mini fridge. N/A is offered on condition checks only. It
   is not applied to mirrors, the towel rack, or the A/C casing and filter,
   where "does it work" has no clear meaning.
3. The squeak test (pass, fail, Other) applies to each bed frame and mattress.
   The bedbug check (pass, fail, Other) applies to each mattress.
4. Option lists for the cleanliness and secure check types are defined, but no
   item uses them in v1.
5. The condition score (1-4) on a finding exists in the data model and admin
   but is not asked for in the audit screens, to keep taps down. The overall
   room rating (1-4) is asked at wrap-up.
6. "Other" counts as a possible problem, so it shows the action buttons.
7. An answered result can be cleared, which returns the item to unanswered.

**Inventory and seed**

8. *(Confirmed)* A ceiling record and one signage record are seeded for each
   of the bedroom and bathroom, although the PRD inventory table lists no
   ceiling and gives signage as "assorted".
9. "All zones" means bedroom and bathroom. The exterior zone exists as a
   choice but nothing is seeded there and the audit flow does not visit it.
10. *(Confirmed)* Locks, hinges and the threshold are not separate records;
    they are assessed as part of the entry door. The bathroom outlet count is
    seeded as one; correct it per room in admin.
11. RoomStandard has two fields beyond the PRD's key fields, zone and name, so
    that "one per zone" items and same-category items (A/C, A/C casing and
    A/C filter are all HVAC) can be generated and matched. Furnishing and
    Fixture also have a zone, a name and a notes field for the same reason.
12. The A/C unit that the two readings attach to is the HVAC fixture named
    exactly "A/C". If it is renamed in admin, readings are still saved but are
    not linked to a fixture.
13. Storage has no room type (the PRD has four types) and is flagged with an
    "is storage" checkbox. It gets no inventory and cannot be picked for an
    audit.
14. Room 9's extra units are added by the seed command, because the XLRG
    standard is shared with room 10. Bed configuration is seeded as "1 queen"
    ("2 queen" for room 9).
15. Property details (address, lot size and so on) are not in the PRD, so only
    the name and unit count are seeded. Fill in the rest in admin.
16. Inventory is generated once, when a room is created. Changing a standard
    later does not change existing rooms.

**Audit flow**

17. A Finding is stored the first time an item is answered. An item with no
    saved finding is unanswered.
18. An expected item counts as absent when the room has fewer in-service
    records than the standard, matched on kind, category, zone and name. It
    then appears with a "Present?" check (present, missing, Other). Renaming
    an inventory item in admin therefore makes the standard item appear absent.
19. Retired furnishings and fixtures are left out of the audit list.
20. Starting an audit for a room that already has an unfinished audit of the
    same type and cycle year resumes that audit instead of making a second.
    "Save and finish audit" records the end time; a finished audit can still
    be opened and edited.
21. The cycle is stored as a year plus an audit type and shown as, for
    example, "2026 annual". The dashboard and issue filters use the year, so
    spot checks count toward their year.
22. Square footage is asked on the Start step while the room has none, and
    throughout the room's first audit. Decor pieces can be added on the
    Bedroom step of any audit (the PRD's open question about removing both
    steps after the first audit is left open).
23. Each A/C reading's time defaults to the moment it is saved and can be
    edited. A reading is recorded in °F to one decimal place.
24. A failed A/C test is flagged on the wrap-up screen and dashboard. It does
    not open an Issue on its own; use the A/C unit's checks for that.
25. "Within 10 minutes" means up to and including 10:00 between the two
    readings, and a drop of exactly 20.0°F passes.

**Issues and outputs**

26. An Issue is opened only when a problem result has the action fix now, work
    order or capex. A problem with no action picked, or with None, opens no
    Issue (the screen prompts "Pick an action").
27. "Closed" means status done, with today's date and an automatic resolution
    note. If the finding becomes a problem again, an issue the app closed is
    reopened; an issue you marked done yourself is left alone.
28. The issue's title and bucket always follow its finding. The title (for
    example "Chair #2 (Bedroom): Damaged") is what the list shows as the item.
29. New issues start at priority medium. Setting status to done fills in the
    resolved date if it is empty.
30. The issue list has a cycle filter in addition to the four in the PRD, so
    dashboard totals can be checked against the list once there is more than
    one year of data.
31. Dashboard counts include issues of every status opened by that cycle's
    audits. The A/C table lists rooms that have an audit in the cycle, using
    each room's most recent audit; rooms not yet audited are not listed.
32. Deleting an inventory record in admin keeps its past findings (shown as
    "removed item"); retiring it is the better option. Deleting a decor piece
    from the audit screen removes that audit's findings for it and keeps any
    from earlier audits the same way.
33. The smell check counts toward the Start step's unanswered total. Flooring
    type does not count as an unanswered item.

## Not in v1

Per the PRD: offline mode, phone layout, multiple users or roles, a per-room
history view, an audit progress view, and hosted deployment.
