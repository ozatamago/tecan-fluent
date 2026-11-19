# Fluent 780 workflows from labcode

Runs Fluent 780 work written as an [ofplang](https://github.com/ofplang/spec) workflow with
[labcode](https://github.com/ofplang/labcode) (`lc run`), through the SiLA2 server of this repository (the combined
server "Tecan Fluent 780 (All devices)", port 50060). Two workflows, both of which ran as serial scripts on the real
instrument on 2026-11-19:

| workflow | what | serial script that passed |
|---|---|---|
| `colour_water_layout` | the layout check: 22 steps (lid moves, plate A to the BioShake and back, plate B in the reader and through Incubator1) | `realrun_20261119.py`, 15:05-15:15 |
| `colour_water_w01_w21` | the colour-water run-through W01-W21 with several channels at once, the reader (Abs405, Abs600) and the end | `colorwater_20261119.py --scale 0.1`, 17:21-17:57 |

This directory is a separate small package (`fluent780-labcode`); it is not part of the connector and the connector
does not depend on it. Nothing in labcode or the ofplang toolchain is changed. GetTips with several neighbouring
channels from a partly used rack needs the connector at commit `1ea0f73` or later.

## Versions

Written and tested against:

| package | version | source |
|---|---|---|
| labcode | 0.10.10 | ofplang/labcode `7695be3` (Release v0.10.10) |
| ofplang-validate | 0.4.1 | ofplang/validate `22e5022` |
| ofplang-schedule | 0.20.1 | ofplang/schedule `c29e1bb` |
| ofplang-run | 0.20.1 | ofplang/run `136e9be` |
| ofplang spec | v0 current draft | ofplang/spec `6edcfce` |
| sila2 | 0.14.0 | (the `labcode[sila2]` extra) |

## What is where

```
workflows/
  lib/fluent780_types.yaml               Workcell, TipRack, Absorbance (imported by both workflows)
  lib/fluent780_processes.yaml           the processes (imported by both workflows)
  colour_water_layout.workflow.yaml      WHAT happens: portable ofplang v0 (passes `lc validate` in strict mode)
  colour_water_layout.boundary.yaml      WHICH labware: FluentControl labels and lid types of the run
  colour_water_w01_w21.workflow.yaml     W01-W21: wells, volumes, liquid classes, sites, temperatures, waits
  colour_water_w01_w21.boundary.yaml     its labware, tubes, tip racks, lids and the wait scale
  fluent780.env.yaml                     HOW: the labcode environment of both; one x-labcode script per (process, mode)
  fluent780.document.yaml                for `lc schedule` only: where the Workcell starts and ends
  fluent780.run.yaml                     the run manager's configuration (failure policy, cover sites, pacing)
src/fluent780_labcode/
  steps.py        what the environment scripts call around each SiLA2 command (run check, records, waits)
  pipetting.py    one transfer per operation: single channel, or several channels by plate column
  manager.py      the run manager: StartRun, `lc run`, EndRun
  mission.py      the mission directory (mission.json, state.json, events.jsonl)
  cover_sites.py  GetCoverSiteIndex("<holder>") from the FluentControl connector or a fixed table
tests/            offline tests (fake SiLA2 client, loopback fake SiLA2 server, the real run's log as the expectation)
```

Instrument names (labware labels, lid types, tubes, tip racks, sites, wells, volumes, liquid classes, Magellan method
files, temperatures, waits and the wait scale) are only in the workflows, the boundaries and the run configuration.
The connector's feature and command names are in the environment scripts and, for pipetting, in `pipetting.py`.
A test checks that the helper package holds no instrument names.

## How the Fluent 780 maps onto ofplang / labcode

| Fluent 780 | ofplang / labcode |
|---|---|
| The FluentControl run (StartRun ... EndRun) | The `Workcell` Object. It enters and leaves at the run boundary; its view names the mission directory, where the run manager recorded the run it opened. Every process takes it in `state` and hands it on (`objects.map`) |
| The order of the steps | The `Workcell` chain: each node reads the previous node's `cell`, so the steps form one dependency chain and `lc schedule` / `lc run` keep exactly that order |
| Lid off / on, plate moves | `remove_lid`, `put_lid_on`, `move_plate` (Labware.TransferLabware), `transfer_plate` (PlateTransfer.MoveLabware); registering a lid is `add_lid` |
| One pipetting transfer (GetTips ... DropTips) | One process, so one labcode operation and one SiLA2 connection: `transfer_liquid` (one channel, a new tip per target well, optional mix with the same tip), `transfer_liquid_multi` (several channels, one plate column at a time), `mix_wells_multi` (new tips for mixing only) |
| Temperatures | `set_plate_temperature` (CPLC slot), `set_shaker_temperature`, `wait_shaker_temperature` (BioShake.ReadTemperature until reached), `shaker_temperature_off`, `lock_shaker_plate`, `unlock_shaker_plate`, `set_incubator_temperature` |
| Incubator1 with shaking | The composites `shake_in_incubator` (via Regrip, close, shake, back, close) and `incubate_with_shaking` (temperature, then that) |
| Reader, camera, waits | `measure_absorbance`, `take_photo`, `hold` (seconds x scale) |
| Plates, lids, tubes, the trough | Pure Data (their FluentControl labels), supplied at the run boundary |
| Tip racks | Pure Data of type `TipRack` (tip type, rack, whether to send SetNextTipPosition before a single tip), at the run boundary |
| Absorbance results | Pure Data outputs of type `Absorbance` (method, result file, labels, wells, values, note); in `--boundary-out` and `--observation-out` |
| The SiLA2 server | Device `fluent_control` (one spot, `deck`) with an `x-labcode.connection`; every mode holds it, so no two operations overlap |

Why plates and lids are not Objects here: in labcode an Object rests on a spot, a spot holds one Object, and a mode
fixes the spot of each port. Moving labware between deck positions as Objects would need the deck positions as
spots, the RGA as a transporter (with Regrip_Pos as a relay, `--max-transport-legs 2`) and the moves as labcode
transports planned by the scheduler. That gives the order of moves to the scheduler, while these runs are fixed
sequences checked for RGA clearance step by step. See "Open questions".

### Several channels at once

`transfer_liquid_multi` and `mix_wells_multi` take the target wells in the order given and group them by plate
column (wells of one column are 18 mm apart and the channels spread to them). For each group, neighbouring channels
1..k take new tips, where k is at most the tips left in the current column of the rack (`Deck.TipRacks`, "next tip
F4" leaves 3): the rest of the group is the next round. With two tips left, three wells are 2 + 1, as on
2026-11-19. Each tip aspirates from the same source well (a trough lane), the tips dispense into the column's wells,
optionally mix there, and are dropped together. All of it is one labcode operation.

## Running it

The run manager opens the FluentControl run, runs `lc run`, and ends the run. Running `lc run` on a workflow
directly is refused by the first operation (there is no mission, so there is no run to check against).

```sh
pip install -e integrations/labcode        # labcode[sila2]==0.10.10 and this package, in one interpreter
W=integrations/labcode/workflows

# offline checks (no instrument)
lc validate $W/colour_water_w01_w21.workflow.yaml
lc schedule schedule $W/colour_water_w01_w21.workflow.yaml --env $W/fluent780.env.yaml \
  --document $W/fluent780.document.yaml -o plan.yaml

# the real run (moves the instrument)
python -m fluent780_labcode run $W/colour_water_w01_w21.workflow.yaml \
  --env $W/fluent780.env.yaml --boundary $W/colour_water_w01_w21.boundary.yaml \
  --config $W/fluent780.run.yaml --missions missions/
```

The layout check is the same with `colour_water_layout.workflow.yaml` and `colour_water_layout.boundary.yaml`.

- Before a run, check the boundary against the deck: labels, which tubes hold what, the tip racks (the deck state's
  next tip of each partly used rack), and `wait_scale` (1 = the protocol's times; 0.1 was used on 2026-11-19 as a flow
  check). The incubator's 10 s shake is not scaled. W10 sends the 37 C command only (no 60 min hold), as agreed on
  2026-11-19.
- Where it runs. The environment points at `10.5.1.156:50060`. From a Mac with the SSH forwarding to the Fluent PC,
  give `--endpoint 127.0.0.1:50060` (or edit the environment). The cover-site indices (below) are resolved through the
  UniteLabs FluentControl connector, which only listens on the Fluent PC; elsewhere, put them in `cover_sites.static`.
- labcode runs every operation in its own process with its own SiLA2 connection. Connecting to the combined server
  fetches all of its feature definitions, so expect some seconds of overhead per operation (75 operations for
  W01-W21, 27 for the layout check; each pipetting transfer is one of them).
- Exit codes: 0 the workflow completed and the run was ended; 1 it failed (see the mission's `state.json`); 2 the
  documents were refused before anything was sent.

### The mission directory

Each run gets `missions/<timestamp>-<id>/` (the mission id is the directory name):

- `mission.json`: the mission id, the server, `RunStarted` and `RecordFolder` of the run, the failure policy, the
  cover-site configuration;
- `state.json`: OPENING, ACTIVE, VERIFYING, CLOSING, COMPLETED; after a failure RUN_ENDED, UNCERTAIN or REFUSED;
- `events.jsonl`: every command before it is sent and its result or error afterwards (with the mission id and the
  process id), state changes, cover-site resolutions, temperature readings, waits, notes;
- the workflow (with its `$import`s expanded), environment and boundary that were run, and what `lc run` wrote:
  `status.yaml`, `result_boundary.yaml`, `observation.yaml`, `lc_run.log`.

### Run boundaries and failures

Following the labcode run management specification for this instrument (2026-11-14):

1. Before anything is sent: the workflow passes the portable-v0 front door and the environment the labcode dialect
   front door.
2. If a FluentControl run is already open, the mission is refused (REFUSED); it never joins or ends someone else's run.
3. StartRun once; `RunStarted` and `RecordFolder` are recorded.
4. `lc run`. Before every command, the operation checks that `RunOpen` is true and `RunStarted` is the recorded
   one; otherwise it sends nothing and fails. Operations never resend a command, never start a run and never clean up
   (no DropTips after a failed pipetting command).
5. When every activity completed: the run is checked to be ours, EndRun once, and `RunOpen` must be false (COMPLETED).

**Failure policy: `end-run` is the default** (decided 2026-11-19). It is what the user's serial runs did on the real
instrument (`realrun_20261119.py`, `colorwater_20261119.py`, `multitest_20261119.py`: on a failure, EndRun if a run
was open). After a failure, once labcode has stopped, the run manager checks that the open run is still this
mission's (`RunOpen`, `RunStarted`) and sends EndRun once (RUN_ENDED); FluentControl drops mounted tips at EndRun.
If the run is not ours or cannot be read, nothing is sent (UNCERTAIN). This is a conditional EndRun, not the
unconditional one in a `finally` that the 2026-11-14 specification (section 3.3) forbids.

`hold` (`on_failure: hold` in the run configuration, or `--on-failure hold`) sends nothing and leaves the run open
for an operator (UNCERTAIN), as section 3 of the specification describes; use it when the state after a failure
must be inspected before anything else is sent.

A command that times out (`settle`, 600 s per command, 900 s for a measurement; `op_timeout` 1800 s per operation)
fails the operation, but the instrument may still be carrying it out: SiLA2 cannot cancel it.

Two things are notes rather than failures, as in the serial script: an AddLabware refused with "already exists" (the
lid is in FluentControl's record already) and a failed photo. A measurement whose result file the server cannot find
is a note only where the workflow says `allow_missing_result: true` (Abs600.mth for now, whose result file is written
where the server does not look yet); its reading then has no values and the server's message as its note.

### Cover sites

Putting a lid on uses `Labware.TransferLabware(lid, 'GetCoverSiteName("<holder>")', <index>)` as the serial scripts
did (`PutLidOn` is refused for plates the connector tracks, such as plate B, and stalls FluentControl when the lid
is already there). The index is `GetCoverSiteIndex("<holder>")`, read either from `cover_sites.static` in the run
configuration or, right before each lid move, from the UniteLabs FluentControl connector
(`RuntimeController.ResolveExpression`; `port: auto` finds the connector on the Fluent PC). A holder with no known
index fails the operation before anything is sent.

## Tests

```sh
cd integrations/labcode
pytest -m "not integration"   # about 20 s
pytest                        # also lc run against a loopback fake server (several minutes)
```

- `test_colour_water.py` (W01-W21, in-process fake SiLA2 client): the server receives exactly the commands of the
  2026-11-19 17:21 run in the same order and with the same arguments (236: StartRun, the 233 commands EndRun
  reported, the photo and EndRun; read from `tests/fixtures/colorwater_20261119_run2.log` by `tests/runlog.py`);
  the waits are the log's (protocol times x 0.1) plus the unscaled 10 s shake; the multi-channel groups split as in
  the log (1000 ul: 2, 2, 2, 1+1, 3, 1, 3, 3, 3, 2+1; 200 ul mixes: 2+1, 3, 3, 1+2); a 2 + 1 split with two tips left
  in a column; BioShake temperature polling until reached and its timeout; a failure in a multi-channel aspiration,
  at LockPlate or in the Abs405 measurement sends nothing more and ends the run; a missing Abs600 result file is a
  note, a missing Abs405 one a failure; `lc validate` and `lc schedule` (75 operations in W01 ... W21, reader, end
  order).
- `test_manager.py` (the layout check): StartRun, the 5 AddLabware, the 21 commands of the 22 steps (step 19 is the
  10 s wait) and EndRun, with the arguments of `realrun_20261119.py`; a failure at step 1, 7, 12 or 21 ends the run;
  `hold` leaves it open; an already open run is never joined; a run lost in the middle is neither restarted nor
  ended; an already registered lid is kept; an unknown cover site fails before sending.
- `test_documents.py`: `lc validate`, `lc schedule` and the labcode dialect front door for the layout check; no
  instrument names in the helper package.
- `test_steps.py`: the run check, the event records, cover-site resolution, the absorbance result structure.
- `test_lc_run.py` (marked `integration`): the real `lc run` against a loopback fake SiLA2 server that keeps the run
  and the tip racks across connections, as the connector does: the layout check (the same call sequence, each command
  from a process of its own inside one run; a failure at step 7 ending the run) and W01-W21 (the same 236 commands as
  the real run; the readings and the W07 temperature in the result boundary).

The cover-site indices in the tests are made up, and the 200 ul and 1000 ul racks' starting tips are inferred from
the log (where it shows the groups split). Nothing in the tests reaches the instrument or the Fluent PC.

## Open questions

- Plates and lids as Objects (deck positions as spots, the RGA as a transporter, Regrip as a relay), so that
  labcode tracks labware and plans moves. The RGA clearance checks of the connector would then have to accept the
  scheduler's order, and the run manager would have to give the scheduler the deck layout.
- Cover-site indices: resolved per lid move on the Fluent PC, or read once before the run and kept in the run
  configuration (they depend on the layout).
- The fixed CPLC cooling wait (W01): the CPLC temperature can be read now (`CoolingHeatingPlates.ReadTemperature`), so
  the wait could become a read-until-reached like the BioShake's.
- Abs600.mth: once the server finds its result file, set `allow_missing_result: false` for it.
- W10's 60 min recovery is in the LB overnight run, not here; that run is a separate workflow still to be written.
- After lids are put back with `GetCoverSiteName(...)`, the connector's deck state keeps the expression as the lid's
  location (2026-11-18 note); a follow-up `Deck.MoveLabwareRecord` may be needed after the run, as after the serial
  scripts.
