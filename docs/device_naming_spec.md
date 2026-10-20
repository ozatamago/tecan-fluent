# Spec: one hierarchy per device (names, identifiers, folders, server assemblies)

Goal: make the device the top level everywhere - in the SiLA feature identifiers, in the names the UniteLabs App
shows, in the source folders, and in the server assemblies - so that a user sees "which device, then which
function". Behaviour does not change: command, property, parameter and response names, their docstrings, error
names, the XML sent to FluentControl and the Fluent PC paths stay as they are.

Work on a branch `refactor/device-hierarchy`, one commit per step below, Conventional Commits, every commit ends with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push and do not contact any remote host.
`uv run pytest -q` (137 tests before you start), `uv run ruff check` and `uv run ruff format --check` must pass
before every commit.

## 1. Feature identifiers and display names

Every feature keeps `originator="jp.riken.bdr"` and `version="1.0"`. Set `category`, `identifier` and
`display_name` explicitly (the CDK `sila.Feature.__init__` accepts `identifier=` and `display_name=`), and rename the
Python class to the new identifier.

| Device | Old (category/Identifier) | New category | New identifier | Display name |
|---|---|---|---|---|
| Fluent | fluent/RunController | tecan.fluent | RunControl | Fluent - Run (Start / End) |
| Fluent | odtc/StatusController | tecan.fluent | Status | Fluent - Status |
| FCA arm | fluent/LiquidHandling | tecan.fluent.arm | LiquidHandling | FCA Arm - Liquid Handling |
| RGA gripper | fluent/RgaController | tecan.fluent.gripper | PlateTransfer | RGA Gripper - Move & Return Plate |
| RGA gripper | fluent/LabwareController | tecan.fluent.gripper | Labware | RGA Gripper - Labware, Lids & Fingers |
| Deck cameras | fluent/DeckCamera | tecan.fluent.camera | DeckCamera | Deck Cameras |
| ODTC | odtc/DoorController | inheco.odtc | Door | ODTC - Door |
| ODTC | odtc/MethodController | inheco.odtc | Methods | ODTC - Temperature Programs |
| ODTC | odtc/TemperatureController | inheco.odtc | Temperatures | ODTC - Temperatures |
| Infinite | platereader/TrayController | tecan.infinite | Tray | Infinite - Tray |
| Infinite | platereader/AbsorbanceReader | tecan.infinite | Absorbance | Infinite - Absorbance |
| Infinite | platereader/FluentPlateHandling | tecan.infinite | PlateHandling | Infinite - Plate In / Out (RGA) |
| BioShake | fluent/BioShakeController | qinstruments.bioshake | BioShake | BioShake - Shake & Heat |
| Inheco incubator | fluent/ShakingIncubatorController | inheco.incubator | ShakingIncubator | Inheco Incubator - Shake & Heat |
| Inheco CPLC | fluent/TemperaturePositionController | inheco.cplc | CoolingHeatingPlates | Cooling / Heating Plates (CPLC 1-3) |
| Incubator1 | fluent/Incubator1Controller | tecan.incubator1 | Incubator1 | Incubator1 - Temperature, Shaker & Door |
| Demo | fluent/ColorMixDemo | demo | ColorMix | Demo - Color Mix & Measure |

Use a plain ASCII hyphen-minus in display names (SiLA display names allow it; check the CDK accepts the `&`, `/`,
`(`, `)` characters and fall back to "and" / "-" if it does not). The feature docstring stays the feature
description; where it names another feature by its old name (e.g. "RunController.StartRun",
"FluentPlateHandling.MeasureWorktablePlate", "AcceptDefinitionChanges in RunController"), update the reference to the
new name. Do the same in error messages that name a feature (e.g. "Start a run first (RunController.StartRun)" ->
"(RunControl.StartRun)").

Custom data types (`OdtcMethodInfo`, `OdtcTemperatures`, `MeasurementResult`, ...) keep their names; they move with
their feature.

## 2. Folders: device first

Keep the template's `features/` and `io/` split, and under each, one folder per device:

```
src/unitelabs/tecan_fluent/
  apps/
    fluent780_all.py      everything (today apps/fluent780.py): the combined "Tecan Fluent 780 (All devices)" server
    fluent780.py          Fluent itself: RunControl, Status, LiquidHandling, PlateTransfer, Labware, DeckCamera
    infinite.py           Tray, Absorbance, PlateHandling, Status (today apps/infinite_fluent.py)
    infinite_usb.py       unchanged content (direct USB reader), renamed features
    odtc.py               Door, Methods, Temperatures, Status (kept for completeness; the standalone server is the
                          separate inheco-odtc repository)
    bioshake.py           BioShake, Status
    inheco_incubator.py   ShakingIncubator, Status
    cplc.py               CoolingHeatingPlates, Status
    incubator1.py         Incubator1, Status
    colormix_demo.py      ColorMix plus what it needs (RunControl, Status, Absorbance, LiquidHandling, DeckCamera)
  features/
    fluent/        run_control.py  status.py
      arm/         liquid_handling.py
      gripper/     plate_transfer.py  labware.py
      camera/      deck_camera.py
    odtc/          door.py  methods.py  temperatures.py  errors.py (OdtcOperationFailed)
    infinite/      tray.py  absorbance.py  plate_handling.py
    bioshake/      bioshake.py
    inheco_incubator/  shaking_incubator.py
    cplc/          cooling_heating_plates.py
    incubator1/    incubator1.py
    demo/          colormix.py
  io/
    fluentcontrol/ backend.py (today fluent_backend.py) definitions.py remote.py fc_log.py progress.py
    fluent/arm/    smart_xml.py and the liquid-handling XML builders (move them out of the feature module, which
                   removes the io -> features import noted in the last restructuring)
    fluent/gripper/ labware_tracker.py and the labware XML builders
    fluent/camera/ deck_cameras.py
    odtc/          method_store.py, the ODTC macro XML
    infinite/      asc.py reader.py xml.py plr_reader.py
    bioshake/ inheco_incubator/ cplc/ incubator1/   the device macro XML builders (today in features/temperature_devices.py)
  data/            unchanged
tests/   the same device folders under tests/features, tests/io and tests/apps
```

`unitelabs.tecan_fluent:create_app` must keep starting the combined server (it is what the Fluent PC task runs);
keep the lazy loading of `__init__.py` that avoids the "Multiple configurations" CDK error.

## 3. Server assemblies and example configs

- `apps/fluent780_all.py`: the combined server, same features as today (19 including the two SiLA core features) and
  same UUID `7c3f1e9a-2b5d-4a8e-b6c4-0d1f2e3a4b50` and port 50060. Default server name "Tecan Fluent 780 (All
  devices)", description shortened to one or two sentences.
- One app per device as in the tree above, each with its own config class, default name, `type`, a one- or
  two-sentence description, and a new fixed UUID (generate once, write it into the example config), ports:
  fluent780 50062, infinite 50063, bioshake 50064, inheco_incubator 50065, cplc 50066, incubator1 50067,
  colormix_demo 50068 (50061 is the inheco-odtc repository).
  Server names: "Tecan Fluent 780", "Tecan Infinite 200 PRO", "BioShake", "Inheco Shaking Incubator",
  "Inheco CPLC (3 positions)", "Incubator1 (6 positions)", "ColorMix Demo".
- Every device app that talks to FluentControl creates one `FluentOdtcBackend` (rename the class to
  `FluentControlBackend`, keep an alias only if needed by tests) with its own `definitions.local_dir`
  (`C:\Users\Tecan\OFML\state\<app>` in the Fluent PC example) so servers on the same PC never share local pending
  files. Records stay in the common `C:\Users\Tecan\OFML\records`.
- `config/`: one `<app>.fluentpc.example.json` per app (hostname 10.5.1.156, `ssh_target` "local", UniteLabs
  connector at 127.0.0.1:51822) and keep the existing dry-run examples working.
- `scripts/windows/start_connector.ps1` and `register_server_task.ps1`: take `-App` (module name) and `-Config`
  parameters and a task name `OFML_<App>Server`; the defaults must stay exactly what the current task uses (the
  combined server, `config.fluent780.json`, task `OFML_Fluent780Server`).

## 4. Tests and documentation

- A test that, for every app, lists the fully qualified feature identifiers and display names and compares them with
  the table in section 1 (including that the combined app has exactly the 17 device features plus the two core
  features).
- A test that every app's example config loads and that UUIDs and ports are unique across apps.
- Keep a mapping table old -> new identifier in `docs/feature_identifiers.md` (for anyone with scripts using the old
  identifiers) and link it from the README and CHANGELOG.
- README: a "Devices and servers" table (device, server name, port, features), the new layout tree, and how to run
  a device server (`connector start --app unitelabs.tecan_fluent.apps.<app>:create_app -cfg config/<app>.json`).

## Done when

- Tests, ruff check and ruff format are clean; the identifier/display-name test matches section 1 exactly.
- Each app starts in dry-run mode bound to 127.0.0.1 with discovery off and lists its features through a sila2
  client (do this locally only).
- `git grep -n "RunController\|StatusController\|RgaController\|LabwareController\|DoorController\|MethodController\|TemperatureController\|TrayController\|AbsorbanceReader\|FluentPlateHandling\|BioShakeController\|ShakingIncubatorController\|TemperaturePositionController\|Incubator1Controller\|ColorMixDemo"`
  finds the old names only in `docs/feature_identifiers.md`, CHANGELOG.md, this spec and the earlier restructure spec.
