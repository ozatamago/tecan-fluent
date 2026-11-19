# Fluent 780 workflows from labcode

Runs Fluent 780 work written as an [ofplang](https://github.com/ofplang/spec) workflow with
[labcode](https://github.com/ofplang/labcode) (`lc run`), through the SiLA2 server of this repository (the combined
server "Tecan Fluent 780 (All devices)", port 50060). The first workflow is the colour-water layout check of
2026-11-19: the same 22 steps as the serial script `realrun_20261119.py`, which passed on the real instrument that day
(15:05-15:15).

This directory is a separate small package (`fluent780-labcode`); it is not part of the connector and the connector
does not depend on it. Nothing in labcode or the ofplang toolchain is changed.

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
  colour_water_layout.workflow.yaml   WHAT happens: portable ofplang v0 (passes `lc validate` in strict mode)
  colour_water_layout.env.yaml        HOW: the labcode environment; one x-labcode script per (process, mode)
  colour_water_layout.boundary.yaml   WHICH labware: FluentControl labels and lid types of this run
  colour_water_layout.document.yaml   for `lc schedule` only: where the Workcell starts and ends
  fluent780.run.yaml                  the run manager's configuration (failure policy, cover sites, pacing)
src/fluent780_labcode/
  steps.py        what the environment scripts call around each SiLA2 command
  manager.py      the run manager: StartRun, `lc run`, EndRun
  mission.py      the mission directory (mission.json, state.json, events.jsonl)
  cover_sites.py  GetCoverSiteIndex("<holder>") from the FluentControl connector or a fixed table
tests/            offline tests (fake SiLA2 client and a loopback fake SiLA2 server)
```

Instrument names (labware labels, lid types, sites, the Magellan method file, temperatures) are only in the workflow,
the boundary and the run configuration; the feature and command names of the connector are only in the
environment scripts. `steps.py` knows neither (a test checks this).

## How the test maps onto ofplang / labcode

| Fluent 780 | ofplang / labcode |
|---|---|
| The FluentControl run (StartRun ... EndRun) | The `Workcell` Object. It enters and leaves at the run boundary; its view names the mission directory, where the run manager recorded the run it opened. Every process takes it in `state` and hands it on (`objects.map`) |
| The order of the 22 steps | The `Workcell` chain: each node reads the previous node's `cell`, so the steps form one dependency chain and `lc schedule` / `lc run` keep exactly that order |
| Lid off / lid on / plate move / tracked plate move / measure / incubator commands / wait | Atomic processes `remove_lid`, `put_lid_on`, `move_plate` (Labware.TransferLabware), `transfer_plate` (PlateTransfer.MoveLabware), `measure_absorbance`, `set_incubator_temperature`, `close_incubator_door`, `start_incubator_shaker`, `stop_incubator_shaker`, `hold`; registering a lid is `add_lid` |
| Steps 14-22 (incubate with shaking) | The composite process `incubate_with_shaking` |
| Plates, lids, tip racks, the trough | Pure Data (their FluentControl labels), supplied at the run boundary |
| The absorbance result | Pure Data output `reading_b` of type `Absorbance` (method, result file, labels, wells, values); in `--boundary-out` and `--observation-out` |
| The SiLA2 server | Device `fluent_control` (one spot, `deck`) with an `x-labcode.connection`; every mode holds it, so no two operations overlap |
| One SiLA2 command | The mode's `x-labcode.script` (flavor `sila2`), calling `fluent780_labcode.steps.Step` |
| The 10 s shake | The `hold` process (a timed wait inside the run) |

Why plates and lids are not Objects here: in labcode an Object rests on a spot, a spot holds one Object, and a mode
fixes the spot of each port. Moving labware between deck positions as Objects would need the deck positions as
spots, the RGA as a transporter (with Regrip_Pos as a relay, `--max-transport-legs 2`) and the moves as labcode
transports planned by the scheduler. That is the natural next step for workflows where the scheduler should choose
the moves, but it gives the order of moves to the scheduler, while this test is a fixed sequence that was checked
for RGA clearance step by step. See "Open questions".

## Running it

The run manager opens the FluentControl run, runs `lc run`, and ends the run. Running `lc run` on the workflow
directly is refused by the first operation (there is no mission, so there is no run to check against).

```sh
pip install -e integrations/labcode        # labcode[sila2]==0.10.10 and this package, in one interpreter

# offline checks (no instrument)
lc validate integrations/labcode/workflows/colour_water_layout.workflow.yaml
lc schedule schedule integrations/labcode/workflows/colour_water_layout.workflow.yaml \
  --env integrations/labcode/workflows/colour_water_layout.env.yaml \
  --document integrations/labcode/workflows/colour_water_layout.document.yaml -o plan.yaml

# the real run (moves the instrument)
python -m fluent780_labcode run integrations/labcode/workflows/colour_water_layout.workflow.yaml \
  --env integrations/labcode/workflows/colour_water_layout.env.yaml \
  --boundary integrations/labcode/workflows/colour_water_layout.boundary.yaml \
  --config integrations/labcode/workflows/fluent780.run.yaml \
  --missions missions/
```

- Where it runs. The environment points at `10.5.1.156:50060`. From a Mac with the SSH forwarding to the Fluent PC,
  give `--endpoint 127.0.0.1:50060` (or edit the environment). The cover-site indices (below) are resolved through the
  UniteLabs FluentControl connector, which only listens on the Fluent PC; elsewhere, put them in `cover_sites.static`.
- labcode runs every operation in its own process with its own SiLA2 connection. Connecting to the combined server
  fetches all of its feature definitions, so expect some seconds of overhead per operation (27 operations here).
- Exit codes: 0 the workflow completed and the run was ended; 1 it failed (see the mission's `state.json`); 2 the
  documents were refused before anything was sent.

### The mission directory

Each run gets `missions/<timestamp>-<id>/` (the mission id is the directory name):

- `mission.json`: the mission id, the server, `RunStarted` and `RecordFolder` of the run, the failure policy, the
  cover-site configuration;
- `state.json`: OPENING, ACTIVE, VERIFYING, CLOSING, COMPLETED; after a failure RUN_ENDED, UNCERTAIN or REFUSED;
- `events.jsonl`: every command before it is sent and its result or error afterwards (with the mission id and the
  process id), state changes, cover-site resolutions, waits;
- the workflow, environment and boundary that were run, and what `lc run` wrote: `status.yaml`,
  `result_boundary.yaml`, `observation.yaml`, `lc_run.log`.

### Run boundaries and failures

Following the labcode run management specification for this instrument (2026-11-14):

1. Before anything is sent: the workflow passes the portable-v0 front door and the environment the labcode dialect
   front door.
2. If a FluentControl run is already open, the mission is refused (REFUSED); it never joins or ends someone else's run.
3. StartRun once; `RunStarted` and `RecordFolder` are recorded.
4. `lc run`. Before every command, the operation checks that `RunOpen` is true and `RunStarted` is the recorded
   one; otherwise it sends nothing and fails. Operations never resend a command, never start a run and never clean up.
5. When every activity completed: the run is checked to be ours, EndRun once, and `RunOpen` must be false (COMPLETED).

After a failure the run manager follows `on_failure` (run configuration, or `--on-failure`):

- `end-run` (default; what `realrun_20261119.py` did): after labcode has stopped, if the open run is still this
  mission's, EndRun once (RUN_ENDED). If the run is not ours or cannot be read, nothing is sent (UNCERTAIN).
- `hold`: nothing is sent and the run stays open for an operator (UNCERTAIN), as section 3 of the 2026-11-14
  specification asks.

A command that times out (`settle`, 600 s per command, 900 s for the measurement; `op_timeout` 1800 s per operation)
fails the operation, but the instrument may still be carrying it out: SiLA2 cannot cancel it.

### Cover sites

Putting a lid on uses `Labware.TransferLabware(lid, 'GetCoverSiteName("<holder>")', <index>)` as the serial script
did (`PutLidOn` is refused for plates the connector tracks, such as plate B, and stalls FluentControl when the lid
is already there). The index is `GetCoverSiteIndex("<holder>")`, read either from `cover_sites.static` in the run
configuration or, right before each lid move, from the UniteLabs FluentControl connector
(`RuntimeController.ResolveExpression`; `port: auto` finds the connector on the Fluent PC). A holder with no known
index fails the operation before anything is sent.

## Tests

```sh
cd integrations/labcode
pytest -m "not integration"   # seconds
pytest                        # also lc run against a loopback fake server (about 2 minutes)
```

- `test_documents.py`: `lc validate` (strict portable v0), `lc schedule` (the plan keeps the 27 operations in the
  script's order), the labcode dialect front door, and no instrument names in the helper package.
- `test_manager.py` (in-process fake SiLA2 client, the environment scripts run in workflow order): the instrument
  receives exactly StartRun, the 5 AddLabware, the 21 commands of the 22 steps (step 19 is the 10 s wait) and
  EndRun, with the same arguments as `realrun_20261119.py`; a failure at step 1, 7, 12 or 21 sends nothing more
  and ends the run; `hold` leaves it open; an already open run is never joined; a run lost in the middle is neither
  restarted nor ended; an already registered lid is kept; an unknown cover site fails before sending.
- `test_steps.py`: the run check, the event records, cover-site resolution, the absorbance result structure.
- `test_lc_run.py` (marked `integration`): the real `lc run` against a loopback fake SiLA2 server that keeps the run
  across connections, as the connector does: the same call sequence, each of the 26 commands sent from a process of its own inside one run,
  the reading in the result boundary; and a failure at step 7 ending the run.

The cover-site indices in the tests are made up. Nothing in the tests reaches the instrument or the Fluent PC.

## Open questions

- Failure policy. The 2026-11-14 specification forbids an unconditional EndRun after a failure; the serial script
  ended the run after a failure when a run was open. The default here is `end-run`, but only for a run proven to be
  this mission's and only after labcode has stopped; `hold` is the specification's behaviour. Which one should be the
  default?
- Plates and lids as Objects (deck positions as spots, the RGA as a transporter, Regrip as a relay), so that
  labcode tracks labware and plans moves. The RGA clearance checks of the connector would then have to accept the
  scheduler's order, and the run manager would have to give the scheduler the deck layout.
- Cover-site indices: resolved per lid move on the Fluent PC, or read once before the run and kept in the run
  configuration (they depend on the layout).
- Several commands per operation (e.g. GetTips ... DropTips) for the liquid-handling steps of the full colour-water
  protocol (W01-W21), to save the per-operation connection overhead; the specification already suggests this.
- After lids are put back with `GetCoverSiteName(...)`, the connector's deck state keeps the expression as the lid's
  location (2026-11-18 note); a follow-up `Deck.MoveLabwareRecord` may be needed after the run, as after the serial
  script.
