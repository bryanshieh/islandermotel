# Islander Motel room audit app (v1)

An internal web app that records a yearly condition audit of the Islander
Motel's 34 guest rooms and turns the findings into a prioritized fix list.
The product spec is [docs/PRD.md](docs/PRD.md). This build covers PRD phases
0 to 4: setup, data model, audit flow, issues and dashboard, plus the changes
Bryan asked for after the first test run (listed under "Changes from the
first PRD").

Stack: Django 5.2, SQLite, Django admin and built-in login, server-rendered
templates with HTMX, and Pico CSS. HTMX and Pico load from a CDN, so the
browser needs internet access. There is no JavaScript build step.

The app is self-hosted: it runs on the laptop, and a phone or tablet can use
it over wifi (see "Use it from your phone").

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

After pulling a new version, run `pip install -r requirements.txt` and
`python manage.py migrate` again before starting the app.

## Use it from your phone

The laptop is the server and the phone is the screen. Nothing is hosted
online, so it costs nothing, and it works whenever the laptop is on, awake
and running the app.

### On the same wifi

1. *(Confirmed)* Every inventory item gets one condition check (OK, worn,
   damaged, missing, not working, intermittent, N/A, Other). It covers both
   the item's state and whether it works; there is no separate function check.
2. The function check type and its option list still exist in the data model
   but no item uses them.
3. The squeak test (pass, fail, Other) applies once to the whole bed and sits
   on the bed frame. The bedbug check (pass, fail, Other) applies to each
   mattress.
4. To use the laptop's Tailscale number instead of its name, start the app
   with `python manage.py serve_phone --host 100.x.y.z`.

### Safety on shared wifi

- `serve_phone` makes the app reachable by every device on the same network.
  The login still protects it, and photos need a login too, so use a strong
  password.
- Over plain wifi the connection is not encrypted, so someone on the same
  network with the right tools could read the password as you log in. Do not
  use `serve_phone` on the guest wifi. Tailscale encrypts the connection and
  is the safer choice.
- `runserver` only answers the laptop itself. Use it when you do not need the
  phone.

### Photos from the phone

On a problem item, open "Photo (optional)" and tap "Choose File"; the phone
offers the camera or the photo library. Photos are shrunk to 1600 pixels on
the longest side and saved as JPEG (a 10 MB photo becomes well under 1 MB),
turned upright, and stored in `media/` on the laptop.

To run the automated tests:

```bash
python manage.py test
```

## Using it

- **Audits** (home page): pick a room, audit type and cycle year, then walk
  through Start, Bedroom, Bathroom, Other and Wrap-up. Every tap on a result
  button is saved straight away, so you can leave at any point and resume from
  the saved audits list. Unanswered items stay marked "Unanswered".
- **Issues**: one row per issue, with filters and "Export this view to CSV".
  Change status in the list, or use Edit for priority, cost estimate, date
  resolved and resolution notes.
- **Dashboard**: issue counts by bucket and room type, and A/C readings per
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

(`.secret_key` is also created there on first run. It does not need backing
up: if it is lost the app makes a new one and you log in again.)

Stop the server, then copy both to another location (an external drive or a
cloud folder) from time to time, and always before upgrading the app:

```bash
cp db.sqlite3 ~/Backups/islander-$(date +%F).sqlite3
cp -R media ~/Backups/islander-media-$(date +%F)
```

To restore, stop the server and copy both back into place. Keep the two
together: the database stores the file names of the photos.

## Changes from the first PRD

Asked for by Bryan after the first test run. `docs/PRD.md` has been revised to
match and lists them under "Revisions".

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
- **Decor** was first added in the bedroom step; it has since moved to the
  Other step (see the Nov 12 changes below).


Added on Nov 11 after Bryan chose self-hosting over a paid or free host:

- **Phone layout.** Screens work at phone width: buttons fill the row, the
  menu and step buttons wrap, and tables turn into one card per row.
- **Self-hosted phone access** through `serve_phone` (same wifi or Tailscale),
  in place of the PRD's hosted deployment, which stays deferred.
- **Photos are shrunk on upload**, and a new photo replaces the old file.
- **One optional general photo per zone** (bedroom and bathroom), added at the
  top of each zone's screen. It is saved on the audit, in `media/zones/`, and
  does not count as an unanswered item or open an issue.
- **Noise measurements.** Peak dB outside the room is entered on the Start
  step, and peak dB inside, measured from the bed, at the top of the Bedroom
  step. Both are optional measurement findings in dB. Wrap-up shows the two
  readings and the difference. There is no pass or fail target.

Changed on Nov 12 after the first phone audit:

- **One action per item.** An item's checks (condition, works, squeak,
  bedbug) share a single action, note and photo, and at most one issue. An
  item with two problems makes one issue, such as "TV (Bedroom): Damaged, Not
  working".
- **N/A clears the rest.** Marking an item's condition N/A hides and clears
  its other checks and its action, and they stop counting as unanswered. The
  note and photo stay.
- **A/C check.** Start records the outside temperature and when the A/C was
  switched on ("A/C on now" saves the time straight away). Wrap-up records
  the outflow air temperature. The app shows outside, outflow, the difference
  and minutes running. There is no pass or fail.
- **Room size.** Length and width are entered on the first audit and the
  square footage is calculated.
- **Other zone.** A new step between Bathroom and Wrap-up for decor and
  anything else not on the standard list. Items are added and deleted there
  without the page reloading. The bedroom's "Add decor" form is gone.
- **Jump to unanswered.** Each zone has a "Go to first unanswered" button at
  the top and a floating "Next unanswered" button showing how many are left.
- **Flooring types** now include LVP.
- **Inventory:** shower handles are part of the shower, and each zone has one
  outlet row covering all its outlets. Chairs stay as separate items.
- **Overall rating removed.**

Consolidated on Nov 13 to cut taps (a standard room went from 63 checks to 40):

- **One check per fixture.** "Works?" is gone. The condition check covers it,
  with Not working and Intermittent in its list.
- **Combined rows:** the A/C with its casing and filter; the heater with its
  pilot; all sconces and lamps; the comforter and pillows as "Bedding"; and
  one Signage row for the whole room.
- **Pillows to replace.** Bedding has a number field for how many pillows
  need replacing. It appears in the issue, for example "Bedding (Bedroom):
  Worn (replace 2 pillows)".
- **Several photos per item.** Every item can have any number of photos; each
  can be removed on its own. A new photo is added, it no longer replaces the
  previous one.
- **One squeak test for the whole bed**, on the bed frame. The bedbug check
  stays on the mattress.
- Walls, ceiling and trim stay separate, as do the bed frame, headboard,
  mattress and box spring, and the two chairs.

Each guest room now starts with 38 inventory records (44 in room 9, which has
two beds and a bedding set for each). A database seeded before this change
needs resetting (see above).

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
   but is not asked for in the audit screens, to keep taps down.
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
12. The A/C outflow reading attaches to the HVAC fixture named exactly "A/C".
    If it is renamed in admin, the reading is still saved but is not linked
    to a fixture.
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
22. Room length and width are asked on the Start step while the room has no
    square footage, and throughout the room's first audit. Square footage is
    length times width, rounded to the nearest whole number.
23. "A/C on now" uses the laptop's clock. The outflow reading's time defaults
    to the moment it is saved and can be edited. Temperatures are recorded in
    °F to one decimal place.
24. The A/C difference is the outside temperature minus the outflow air
    temperature. The app does not judge it and it never opens an Issue; use
    the A/C unit's own checks for that.
25. The outside temperature is the audit's ambient temperature field; there
    is no separate indoor temperature reading.
**Issues and outputs**

26. An Issue is opened only when an item has a problem result and its action
    is fix now, work order or capex. A problem with no action picked, or with
    None, opens no Issue (the screen prompts "Pick an action").
27. "Closed" means status done, with today's date and an automatic resolution
    note. If the finding becomes a problem again, an issue the app closed is
    reopened; an issue you marked done yourself is left alone.
28. An item has at most one Issue per audit. Its title lists every problem
    on the item in check order (for example "TV (Bedroom): Damaged, Not
    working"), and its bucket is the item's action. The title is what the
    issue list shows as the item.
29. New issues start at priority medium. Setting status to done fills in the
    resolved date if it is empty.
30. The issue list has a cycle filter in addition to the four in the PRD, so
    dashboard totals can be checked against the list once there is more than
    one year of data.
31. Dashboard counts include issues of every status opened by that cycle's
    audits. The A/C table lists rooms that have an audit in the cycle, using
    each room's most recent audit; rooms not yet audited are not listed.
32. Deleting an inventory record in admin keeps its past findings (shown as
    "removed item"); retiring it is the better option. Deleting an item from
    the Other step removes that audit's findings for it and keeps any from
    earlier audits the same way.
33. The smell check counts toward the Start step's unanswered total. Flooring
    type does not count as an unanswered item.
34. `serve_phone` runs the app with the Waitress server and DEBUG off, and
    accepts the laptop's own network addresses, any Tailscale `.ts.net` name,
    and anything passed with `--host`. Static files for the admin are served
    by WhiteNoise.
35. Photos are stored at up to 1600 pixels on the longest side, JPEG quality
    80. The original full-size file is not kept. HEIC photos are not read
    directly; iPhones normally convert to JPEG when uploading through the
    browser, and a file the app cannot read shows an error instead of saving.
36. The phone layout applies below 600 pixels wide. Tablet and laptop layouts
    are unchanged.
37. Items added in the Other step are saved as furnishings with the category
    "other" and the name typed in. They get a condition check only.
38. An item's note and photos are stored on its first check (condition, or
    "Present?" for a missing item). The issue's edit page shows them and the
    CSV includes the note.
39. The "Next unanswered" button goes to the next unanswered check below the
    middle of the screen and wraps round to the first. The counts on the step
    buttons at the top refresh when the page is reloaded.
40. The pillow count is 0 to 4 and is stored on the bedding item's condition
    finding. It does not open an issue on its own: mark the bedding worn or
    damaged and pick an action. Marking bedding N/A clears the count.
41. In room 9 each bed has its own Bedding row (a comforter and 2 pillows).
42. The file picker accepts several photos at once from the library. There is
    no limit on photos per item.

## Not in v1

Per the PRD: offline mode, multiple users or roles, a per-room history view,
an audit progress view, and hosted deployment (the app is self-hosted on the
laptop instead).
