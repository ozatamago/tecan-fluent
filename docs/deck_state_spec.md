# Spec: deck state as data (Deck, tip racks, hands-off)

Goal: prepare the connector for a future in which other robots (a mobile robot such as Kachaka, an arm such as
Franka) change what is on the Fluent deck. The Fluent software side must then (1) know what is where from data that
others can change, (2) keep FluentControl's own record of tips and labware in step with the real deck, and (3) never
move while another robot works on the deck. The same features and identifiers serve the Fluent 780 and the Fluent 480.

This spec covers steps 2, 3 and 5 of the plan agreed on 2026-10-21 (step 1 is the base worktable, step 4 the hand-over
positions, step 6 checking the deck with cameras and liquid detection; they are only touched where they meet these).

## Background (what exists today)

- FluentControl resets labware to the worktable definition at the start of every run. Labware added with
  `AddLabware` (statement `AddLabwareDataV1`) exists only until the run ends.
- `io/fluent/gripper/labware_tracker.py` already keeps, on the Fluent PC, where the RGA moved tracked labware
  (`C:\Users\Tecan\OFML\state\labware_positions.json`) and re-registers it at the start of the next run with
  `RemoveLabware` + `AddLabware`. The deck state below generalises this.
- `io/fluentcontrol/shared_lock.py` lets one server at a time use FluentControl; a run held open keeps the lock.
- FluentControl remembers which tips of a rack it has used, across runs. When the real rack differs (a full rack put
  in by hand), `GetTips` searches and takes long (122 s on 2026-10-16) or fails.
- On the Fluent 480, the base worktable will be a copy of "Color Water" (`OFML_480`): carriers, nests, the tip waste,
  the devices, a tip rack (`FCA_ 1000ul Filtered SBS[002]`, with a lid `Lid_DiTiFCA[001]` that the RGA lifts off to a
  free nest before `GetTips`, as the 480 script ColorWater_C1 does) and the liquid sources; plates are not part of it.

## 1. The deck state

A JSON file on the Fluent PC, one per instrument (setting `deck.state_file`, default
`C:\Users\Tecan\OFML\state\deck.json`), read before every use and written atomically (write to a temporary file,
then replace). Entries:

```json
{
  "labware": {
    "Plate_A[001]": {"type": "96 Well Flat", "location": "Nest7mm_Pos_3", "site": 14,
                     "lid": "Lid_9mm[001]", "placed_by": "Franka", "placed_at": "2026-10-21T10:00:00",
                     "contents": {"A1": {"liquid": "water", "volume_ul": 150}}},
    "FCA_ 200ul SBS[001]": {"type": "FCA, 200ul SBS", "location": "Nest7mm_Pos_3", "site": 2,
                            "tips": {"kind": "full", "since": "2026-10-21T09:00:00"}}
  },
  "base_worktable": "OFML_480",
  "version": 12
}
```

- Labware that is part of the base worktable is not listed unless it was moved or removed (then it is listed with
  its real position, or with `"location": null` for "taken off the deck").
- `version` increases on every change; commands that read the deck report the version they used (in the record).
- The existing `labware_positions.json` is migrated into this file (one-time, on first start; keep reading the old
  file if the new one is missing).

## 2. Feature `Deck` (category `tecan.fluent`, identifier `Deck`, name "Fluent - Deck")

Nothing in this feature moves the instrument.

| Command / property | What it does |
|---|---|
| `Layout` (property) | The current deck state: one line per labware ("label: type at location[site] (lid ..., placed by ...)"), plus the base worktable name and the version |
| `PlaceLabware(Label, LabwareType, Location, Site, Lid, PlacedBy)` | Record that a labware was put on the deck (by a person or a robot). Refused if the site is taken in the deck state, if the labware type is not defined in FluentControl, or if the location/site does not exist on the base worktable (checked with the definition index, as `AddLabware` is today) |
| `RemoveLabware(Label, RemovedBy)` | Record that a labware was taken off the deck |
| `MoveLabwareRecord(Label, Location, Site, MovedBy)` | Record that a labware was moved by something other than the RGA |
| `SetContents(Label, Wells, Liquid, Volumes)` | Optional: what is in it (used later for planning and checks) |

Every change is also written to the records (`OFML\records\deck\<time>_<command>.json`) so the history can be
read back.

### Applying the deck state to FluentControl

- `RunControl.StartRun` (and every command that opens its own run) registers, right after the run starts and
  before anything else is sent: for each listed labware, `RemoveLabware` (if the base worktable has a labware of that
  label) then `AddLabware` at its recorded position; for each base-worktable labware recorded as removed,
  `RemoveLabware`. These statements are bookkeeping only (nothing moves) and are recorded like any other step.
- When the RGA moves a labware (PlateTransfer, Labware.TransferLabware, Infinite plate handling), the deck state is
  updated after the move succeeded, as the labware tracker does today. The tracker becomes a view on the deck state.
- Commands that address labware by label (Aspirate, Dispense, TransferLabware, ...) are refused before sending if
  the label is neither in the base worktable nor in the deck state, with a message saying which.

## 3. Tip racks

- `PlaceTipRack(Label, TipType, Location, Site, Kind, PlacedBy)` with `Kind` "full" (a fresh rack) or "as is"
  (a rack taken out earlier and put back). It is a `PlaceLabware` that also records the tip state.
- A rack recorded as "full" is registered at the next run start with `RemoveLabware` + `AddLabware`, so FluentControl
  sees a full rack (a newly added rack is full). Investigate first, on the Fluent 480 and in the FluentControl manual,
  whether FluentControl has a statement that sets the next tip position or refills a rack; if it has, prefer it and
  record which. Until checked on the device, do not rely on either being honoured: `GetTips` keeps its timeout.
- `TipRacks` (property): each rack with its tip type, position and recorded state.
- After `DropTips`/`SetTipsBack` nothing is assumed about the rack; FluentControl's own count stays authoritative
  between refills.

## 4. Hands-off (another robot works on the deck)

Feature `HandsOff` (category `tecan.fluent`, identifier `HandsOff`, name "Fluent - Hands Off"):

| Command / property | What it does |
|---|---|
| `Begin(Who, Reason, MaxMinutes)` | Take the shared FluentControl lock (`shared_lock`) on behalf of `Who` and keep it. Refused while a run is open or any server is sending to FluentControl. Returns a token |
| `End(Token)` | Release it. Optionally triggers a deck check (step 6) |
| `State` (property) | Who holds hands-off, why and since when; empty when free |

- While hands-off is held, every server on the Fluent PC refuses FluentControl commands with
  "hands-off by <Who> (<Reason>, since ...)" (it is the shared lock, so this already works across servers;
  `Fluent - Status` shows it in `CurrentOperation` and `Ready` is false).
- `MaxMinutes` (default 30) bounds it: after that it is released with a warning in the log and the records, so a
  robot that died does not block the Fluent forever. A dedicated small background task in the holding server does
  this; the operating system releases the lock anyway if that server process ends.
- The deck must be changed only while hands-off is held. `PlaceLabware`/`RemoveLabware` may be called while held
  (they only write data); they are refused while a run is open, because FluentControl's run already has its layout.

## 5. Configuration

Per instrument (in the server's config, under `deck`): `state_file`, `base_worktable` (name, checked against the
worktable that `OFML_ApiHost` uses), `handoff_sites` (list of location/site pairs outside robots may use; step 4),
`hands_off_max_minutes`. Location and labware names of the Fluent 480 differ from the 780 (`Nest7mm_Pos_3`,
`96 Well Flat`, `7mm Nest_Riken`, ...); nothing instrument-specific is hard-coded.

## 6. Tests

- Deck state: place / remove / move / version, atomic write, refusal of taken sites and unknown types/locations
  (with a fake definition index), migration from `labware_positions.json`.
- Start of a run in dry-run mode: the exact `RemoveLabware`/`AddLabware` statements generated from a given state,
  in order, and recorded.
- Hands-off: refusal across two backends sharing a lock file (as `test_shared_lock.py`), expiry after
  `MaxMinutes` (with a fake clock), refusal while a run is open.
- Feature identifiers and names in `tests/apps/test_feature_identifiers.py`; add the new features to the
  `fluent780_all` and `fluent780` apps (and later the Fluent 480 app).

## Not in this spec

Moving labware between a hand-over site and working sites (step 4 commands), camera checks (step 6), and the
Fluent 480 server assembly itself.
