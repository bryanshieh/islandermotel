# Islander Motel Room Audit App: PRD

Nov 10, 2026 · Bryan · revised Nov 11, 2026 after the first local test run and again to add phone use and self-hosting (see "Revisions" at the end)

## Overview and goals

Build a small web app that records a condition audit of all 34 Islander Motel rooms once a year and turns the findings into a prioritized fix list. The app replaces the current one-page checklist, which has roughly 60 items per room, free-text notes that can't be filtered, and no history from year to year.

**Goals**

- Capture every audit finding as structured data (item, result, bucket, optional photo), not free text.
- Sort every problem into one of three buckets: fix now, work order, or capital refresh (capex).
- Keep each year's audit so a room's condition can be compared over time.
- Keep entry fast: every item in a zone is listed up front with large, one-tap result buttons.

**Success criteria for the v1 test run (proposed, to confirm)**

- One full room audit completed end-to-end on a laptop without touching a spreadsheet.
- The issue list can be filtered by bucket and room and exported to CSV.
- The summary dashboard shows issue counts by bucket and by room type.
- Audit time per room stays within a target of 20-30 minutes at most, measured during the test.

## Users, context and constraints

The only user for v1 is Bryan, auditing all 34 rooms in person.

- **Device:** laptop, tablet or phone. The phone is the main device for walking rooms and taking photos; the laptop runs the app.
- **Connectivity:** wifi is reliable, so no offline mode.
- **Login:** one account, using Django's built-in authentication.
- **Hosting:** self-hosted on Bryan's laptop. The phone reaches it over the same wifi or over Tailscale, and it only needs to be up while the laptop is on. A paid always-on host is deferred.
- **Room variety:** 4 room types, with minor square-footage differences within each type: SML (7 rooms), STD (20), LRG (5) and XLRG (2), plus Storage as the 35th room. Every room has a queen bed except room 9 (XLRG), which has two.
- **Look and feel:** functional is enough; it does not need to be polished.

## Scope

v1 covers the audit loop end to end: set up rooms, run an audit, triage issues, see the totals.

| In v1 | Out of v1 |
| --- | --- |
| Rooms and room types, with default inventory generated from the type | Offline mode |
| Guided, zone-by-zone audit on a laptop, tablet or phone | Offline use on the phone |
| Findings: condition, function, presence, smell, measurements (A/C test) | Multiple users, roles, contractor access |
| Optional photo on any finding, taken with the phone camera and shrunk on upload | Per-room history view (data is kept, screen is not built) |
| Issues with a light lifecycle: status, cost estimate, resolved date | Audit progress view (for example, 12 of 34 rooms done) |
| Issue list with filters and CSV export | Full maintenance system: assignees, history, priorities beyond a field |
| Summary dashboard: issues by bucket and by room type, A/C test results | Hosted deployment on an always-on server (deferred; see Hosting) |
| Self-hosted access from a phone over wifi or Tailscale | |

## Decisions log

The first table lists scope and workflow decisions. The second lists the technical decisions Bryan has signed off, each with the alternative that was considered.

**Decided**

| Area | Decision |
| --- | --- |
| Users | Just Bryan for now |
| Device | Laptop, tablet or phone; screens work at phone width |
| Connectivity | Wifi, no offline mode |
| Framework | Django, with Postgres as the eventual database |
| Local database | SQLite for the test run, switch to Postgres when hosted |
| Hosting | Self-hosted on the laptop; no paid or free cloud host for now |
| Initial inventory | Auto-generated from room type, corrected during the first audit |
| Audit flow | Guided, zone by zone (bedroom, then bathroom; there is no separate entry zone); every item in a zone is listed, with no result pre-selected; audits can be saved mid-way, resumed later, and saved with unanswered items |
| Issues | Light lifecycle: status, cost estimate, resolved date |
| Photos | Optional on any finding |
| Outputs | Issue list with filters and CSV export; summary dashboard |
| This document | PRD plus a technical build plan, no code until approved; the build is handed to a different model after approval |
| Repository | Git repository at /Users/bryanshieh/Apps/islandermotel (GitHub remote: bryanshieh/islandermotel) |

**Technical decisions (signed off)**

| Decision | Decision | Alternative |
| --- | --- | --- |
| Frontend approach | Server-rendered Django templates with HTMX for the interactive bits; no separate JavaScript build | A React single-page app: more flexible, but a second codebase and build step for one user |
| Setup screens | Use Django admin for rooms, room types, standards and inventory corrections; build custom screens only for the audit and issues | Custom screens for everything: slower to reach a test |
| Styling | One off-the-shelf CSS framework (Bootstrap or Pico) with large touch targets for tablet | Hand-written CSS: no benefit for a test run |
| Photo storage | Local media folder on the laptop; photos are shrunk to 1600 px JPEG on upload and need a login to view. An S3-compatible bucket only if the app is ever cloud-hosted | Bucket from day one: extra setup before any test |
| Login | Django's built-in login, one superuser | None while local: saves nothing meaningful and must be added later |
| Hosting | Self-hosted: the app runs on the laptop (`serve_phone`), reached from the phone over the same wifi or Tailscale. Free, and data stays in one place; it is only up while the laptop is on | A cloud host. Free tiers were ruled out (no lasting disk, expiring databases, sleeping servers); Render at about $8 a month with a disk is the fallback if always-on access is wanted |

## Data model

The model separates **things** (what exists and rarely changes) from **observations** (what was seen on a given audit date). A mattress's condition is never stored on the mattress; it is a Finding on a dated Audit, so history builds up on its own.

Diagram (10 entities): Property has Room types and Rooms; a Room type has Room standards; a Room has Audits and its inventory (Furnishing, Fixture, Building element); a Finding ties an Audit to the inventory item it checked; problem Findings become Issues.

Inventory items hang off a Room, each Audit is one visit to a Room, and a Finding links the two. Only problems become Issues. Room standards define what each room type should contain.

| Entity | Belongs to | Key fields |
| --- | --- | --- |
| Property | none | name, address, city, state, zip, lot size (sq ft), building size (sq ft), year built, unit count (34 guest rooms), notes |
| RoomType | Property | name (SML, STD, LRG, XLRG), default square footage, notes |
| Room | Property, RoomType | room number, floor, square footage, bed configuration, bathroom count, status (active, out of service, under renovation). One Room record is Storage, which holds inventory moving in and out of service and is not audited |
| Furnishing | Room | category (bed frame, headboard, mattress, box spring, comforter, pillow, chair, table, dresser, decor, other), type or model, quantity, purchase date, purchase cost, expected life (years), status (in service, retired) |
| Fixture | Room | category (HVAC, heater, TV, light, outlet, sink, shower, toilet, mirror, smoke detector, towel rack, shower handle, mini fridge, other), location (for example bedroom overhead), make or model, install date, last serviced, expected life (years), status |
| BuildingElement | Room | element (floor, ceiling, wall or drywall, door, lock, hinge, window, trim, threshold, counter, signage, other), zone (bedroom, bathroom, exterior), material or finish (for flooring: carpet, tile or tileboard, picked during the audit), last refinished, notes |
| RoomStandard | RoomType | item kind (furnishing, fixture, building), category or element, expected quantity |
| Audit | Room | cycle (for example 2026 annual), audit type (annual, spot check, new inventory), audit date, auditor, start and end time, ambient temperature (°F), overall rating (1-4), overall notes |
| Finding | Audit | target kind (furnishing, fixture, building; empty for the room-level smell check), target, check type (condition, function, cleanliness, secure, presence, pest, noise, smell, measurement), result (a short option list per check type: OK, worn, damaged, missing, not working or N/A for condition; pass or fail for the squeak and bedbug checks; OK, musty or smoke for smell; every list ends with Other, and every result has a free-text field), condition score (1-4), measurement label, measured value, unit, measured at, action bucket (none, fix now, work order, capex), photo, notes |
| Issue | Finding, Room | title, bucket (fix now, work order, capex), priority (low, medium, high, safety), status (open, scheduled, done, deferred), cost estimate, date opened, date resolved, resolution notes |

**Default inventory per room** (from Bryan; the same list for all four types, with room 9 as the exception). There is no entry zone: every entry is a doorway into the bedroom, so the entry door is a bedroom item.

| Zone | Item | Kind | Quantity | Notes |
| --- | --- | --- | --- | --- |
| Bedroom | Entry door | Building | 1 | Deadbolt, plus doorknob with lock; hinges and threshold are assessed as part of the door |
| Bedroom | Bed frame | Furnishing | 1 | Queen; 2 in room 9 |
| Bedroom | Headboard | Furnishing | 1 | Queen; 2 in room 9 |
| Bedroom | Mattress | Furnishing | 1 | Queen; 2 in room 9 |
| Bedroom | Box spring | Furnishing | 1 | Queen; 2 in room 9 |
| Bedroom | Table | Furnishing | 1 | |
| Bedroom | Chair | Furnishing | 2 | |
| Bedroom | TV | Fixture | 1 | |
| Bedroom | Overhead light | Fixture | 1 | |
| Bedroom | Sconce or lamp | Fixture | 2 | |
| Bedroom | Mirror | Fixture | 1 | |
| Bedroom | A/C | Fixture | 1 | |
| Bedroom | A/C casing | Fixture | 1 | |
| Bedroom | A/C filter | Fixture | 1 | |
| Bedroom | Heater | Fixture | 1 | |
| Bedroom | Heater pilot | Fixture | 1 | |
| Bedroom | Dresser | Furnishing | 1 | 2 in room 9 only |
| Bedroom | Comforter | Furnishing | 1 | |
| Bedroom | Decor | Furnishing | Varies by room; counted on the first audit | |
| Bedroom | Pillow | Furnishing | 2 | 4 in room 9 only |
| Bedroom | Outlets | Fixture | 2 | Varies with room and zone |
| Bedroom | Smoke detector | Fixture | 1 | |
| Bedroom | Mini fridge | Fixture | 1 | |
| Bathroom | Light | Fixture | 1 | |
| Bathroom | Mirror | Fixture | 1 | |
| Bathroom | Toilet | Fixture | 1 | |
| Bathroom | Sink | Fixture | 1 | |
| Bathroom | Sink counter | Building | 1 | |
| Bathroom | Shower | Fixture | 1 | Shower head |
| Bathroom | Shower handle | Fixture | 2 | Hot and cold |
| Bathroom | Towel rack | Fixture | 1 | |
| Bathroom | Outlets | Fixture | 1 | Varies with room |
| Both zones | Walls | Building | One per zone | |
| Both zones | Flooring | Building | One per zone | Carpet, tile or tileboard; type differs by zone and is picked during the audit |
| Both zones | Windows | Building | One per zone | |
| Both zones | Trim | Building | One per zone | |
| Both zones | Ceiling | Building | One per zone | |
| Both zones | Signage | Building | One per zone | For example no smoking, do not flush tampons; corrected per room |

"Both zones" means bedroom and bathroom. Each guest room starts with 48 inventory records (55 in room 9).

**Rooms** (from Bryan; square footage is recorded on the first audit; rooms 9, 10 and 201-210 are on the second floor and all others are on the first)

| Room type | Count | Room numbers |
| --- | --- | --- |
| SML | 7 | 7, 11, 12, 14, 15, 20, 21 |
| STD | 20 | 101-110, 201-210 |
| LRG | 5 | 8, 16, 17, 18, 19 |
| XLRG | 2 | 9 (two queen beds), 10 |
| Storage | 1 | Not audited; room number 00 |

**How the pieces work together**

- **Inventory generation.** When a Room is created, the app copies its RoomType's RoomStandard rows into Furnishing, Fixture and BuildingElement records. Each unit becomes its own record (two chairs make two records), so every unit gets its own finding; walls, flooring, windows, trim, ceiling and signage get one record per zone (bedroom and bathroom). Bryan corrects exceptions during the first audit, such as room 9 with two queen beds. New inventory that comes online later is added to the same Furnishing, Fixture or Building tables and can be audited right away.
- **Missing items.** A missing sink counter is found by comparing a room against its standard: the element is expected, so a Finding with result "missing" is raised.
- **A/C test.** The test is two measurement Findings on the room's A/C fixture, one at the start and one at the end, each with a value, unit and timestamp. Elapsed time and temperature drop are calculated, not entered. A room passes when supply-air temperature drops at least 20°F within 10 minutes; rooms that miss are flagged.
- **Issues only for problems.** A Finding with action bucket "none" creates no Issue, so the issue list stays short. A result of N/A is an answer, not a problem.
- **Smell.** One room-level Finding per audit, recorded on the Start step. It has no inventory target; a problem smell can open an Issue like any other finding.
- **Flooring type** is a property of the flooring record (material or finish), not of the audit. It is picked with one tap on the flooring item during the audit.
- **Ambient temperature** lives on the Audit because it is context for the whole visit.

## Audit flow

The audit walks the room in the order Bryan physically moves through it, and each zone lists every item to be answered. No result is pre-selected.

1. **Start.** Pick the room, note the smell on walking in (OK, musty, smoke, Other), record ambient temperature, start the A/C and log the first supply-air reading with its time. On the first audit only, also measure the room and record its square footage on the Room.
2. **Bedroom zone.** Entry door (including its locks, hinges and threshold), lights, outlets, TV, mini fridge, A/C casing and filter, heater pilot, bed and bedding (squeak test of the frame and mattress, bedbug check), chairs, table, dresser, decor (counted on the first audit, with a record added for each piece; a piece added this way can also be deleted from the same screen), floor and its flooring type, ceiling, walls, windows, trim, signage.
3. **Bathroom zone.** Sink, shower and its two handles, toilet, lights, mirror, outlets, towel rack, floor and its flooring type, ceiling, walls, windows, trim, signage.
4. **Wrap-up.** Log the second A/C reading with its time, give an overall rating (1-4), and add notes.
5. **Save.** Each problem logged on the way becomes an Issue; everything marked OK stays a plain record.

**Rules inside each zone**

- Every item in the zone is listed, and no result is pre-selected.
- The list comes from the room's inventory and standard. For each item, Bryan picks a result from that item's short option list (condition lists include N/A; each list ends with "Other"). Every result has a free-text field, shown as soon as a result is picked; for Other it holds the description. For problem items he also sets an action (none, fix now, work order, capex) and can add a photo.
- Items that are expected but absent (from the room's standard) appear in the list so they can be marked missing.
- A/C start and end readings are recorded as measurements. An audit can be saved at any point and resumed later, including with items still unanswered, which stay marked as unanswered.

The screens work on a laptop, tablet or phone, with large buttons and no horizontal scrolling. On a phone the result buttons fill the row and tables become one card per row. Audits outside the annual cycle, such as when new inventory comes online, reuse the same whole-room flow in v1; auditing only selected items is deferred.

## Issue workflow

Every problem found in an audit becomes an Issue in one of three buckets, with a light lifecycle that Bryan can edit in the app.

| Bucket | Meaning |
| --- | --- |
| Fix now | A quick fix, roughly under 10 minutes, done on the spot or the same day |
| Work order | Needs scheduling or a vendor |
| Capex | Replacement or refresh, budgeted separately |

- **Status:** open, scheduled, done, deferred.
- **Fields editable on an issue:** priority (low, medium, high, safety), cost estimate, date resolved, resolution notes.
- **None** is a Finding-level action for a problem that needs nothing done; it does not create an Issue. (The earlier "monitor" action was removed.)
- **Out of v1:** assignees, status history and cost actuals.

**Keeping issues in step with audits.** If a finding is edited after it is saved, for example from damaged to OK, its Issue is updated or closed to match. A new audit cycle opens new Issues, even for an item that is still broken from last year.

## Outputs

v1 has two views, both read-only summaries of the audit data.

**Issue list.** One row per issue with room, item, bucket, priority, status and cost estimate. Filters: bucket, room, room type, status. Export the current filtered view to CSV.

**Summary dashboard.**

- Issue counts by bucket (fix now, work order, capex).
- Issue counts by room type.
- A/C test results per room: start reading, end reading, elapsed minutes, temperature drop, and pass or fail against the 20°F in 10 minutes target.

Counts are shown as absolute numbers, not percentages.

A cycle selector, by year, sets which audit cycle the dashboard shows and defaults to the latest. Storage is excluded from all counts.

## Technical build plan

Django makes sense here: its models map almost one-to-one onto the entities above, and Django admin provides working create, edit and delete screens for the setup data at no extra build cost. The plan is one Django project, one app, server-rendered pages with HTMX for the interactive parts, SQLite locally and Postgres later. The code will live in the Git repository at /Users/bryanshieh/Apps/islandermotel (GitHub remote: bryanshieh/islandermotel).

**Architecture**

- **Framework:** Django with the built-in admin and authentication.
- **Pages:** server-rendered templates, HTMX for the audit result buttons and issue editing.
- **Database:** SQLite for the local test run; switch to Postgres through a settings change when hosting.
- **Files:** photos stored in a local media folder for now; swap to an S3-compatible bucket when hosted.
- **Admin vs custom screens:** admin for rooms, room types, standards and inventory fixes; custom pages for the audit flow, issue list and dashboard.
- **Tests:** automated tests for inventory generation, finding-to-issue creation and the A/C calculations; everything else is checked by hand in the test run.

**Phases**

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 0. Setup | Django project, SQLite, login, base template and CSS | Logs in on the laptop |
| 1. Data model | All entities, migrations, admin screens, RoomStandard-based inventory generation | All 35 rooms (34 guest rooms plus Storage) exist; guest rooms have generated inventory, visible in admin |
| 2. Audit flow | Zone-by-zone audit screens, findings, smell check, A/C measurements, optional photos | A full room audit can be saved from the laptop |
| 3. Issues | Issues created from findings, issue list with filters, status editing, CSV export | A filtered issue list exports to CSV |
| 4. Dashboard | Issue counts by bucket and room type, A/C results table | Dashboard totals match the issue list |
| 5. Test run | Audit a handful of rooms for real, log what slowed down or broke | List of fixes and a decision on hosting |
| 6. Phone use and self-hosting | Phone layout, photo shrinking, `serve_phone` for wifi or Tailscale access | A room is audited from the phone with photos |
| 7. Cloud hosting (deferred, only if always-on access is wanted) | Postgres, bucket storage, managed host | Same app reachable by URL |

Phase 1 depends on knowing the room types and their default inventory; phases 2 to 4 depend only on phase 1.

## Risks and open questions

**Risks**

- **Generated inventory may not match reality.** Rooms within a type can differ, so the first audit doubles as an inventory correction pass.
- **Self-hosted on the laptop.** The app is only reachable while the laptop is on, awake and on the same wifi (or Tailscale). On shared wifi the connection is not encrypted, so the guest network should not be used; Tailscale is the safer route. Photos and the database live on the laptop, so they need backing up: copy the database file and the photo folder to another location from time to time. A one-click export is out of v1.
- **Scope creep.** Per-room history and an audit progress view are tempting and are deliberately left out of v1; the data model already supports both later.
- **Form fatigue.** Listing every item with no default means more taps per room. If an audit takes much longer than the target, a per-zone "all OK" shortcut is the first thing to revisit. Many furnishings are already damaged, so the first audit will likely log many findings and run toward the upper end of the target.

**Open questions**

- [x] What are the per-room quantities for the items marked "To confirm" in the default inventory table?
- [x] Confirm the technical decisions table.
- [ ] After the first audit, remove the square footage and decor-count steps from the audit flow; both are one-time setup captures.

## Revisions

**Nov 11, 2026, after the first local test run** (phases 0 to 4 built)

- Removed the entry zone. Every entry is a doorway into the bedroom, so a separate zone duplicated the bedroom's walls, flooring, windows, trim and signage. "Entry door" is now a bedroom item and covers its locks, hinges and threshold.
- Added a smell check to the Start step.
- Added N/A to the condition results.
- Every result now has a free-text field, not only Other.
- Actions are none, fix now, work order and capex. Monitor was removed.
- Flooring type (carpet, tile or tileboard) is picked on each flooring item during the audit.
- Default inventory: added a mini fridge to the bedroom and outlets to the bathroom; the shower has a shower head and two handles (hot and cold), not two nozzles; ceilings and signage are one per zone.
- Decor pieces added during an audit can be deleted from the same screen.

**Nov 11, 2026, phone use and self-hosting**

- Phone layout moved into scope. The phone is the main device for walking rooms.
- Hosting decision: self-hosted on the laptop, reached from the phone over the same wifi or Tailscale. Free cloud tiers were ruled out and a paid host (about $8 a month) is deferred until always-on access is wanted.
- Photos taken on the phone are shrunk to 1600 px JPEG on upload and need a login to view.
