# Tecan Fluent 780 (RIKEN BDR)

A SiLA 2 connector for the devices built into the Tecan Fluent 780 at RIKEN BDR. Built with the
[UniteLabs CDK](https://docs.unitelabs.io/connector-development/); it drives the devices through FluentControl.

The distribution is `unitelabs-tecan-fluent`, the Python package `unitelabs.tecan_fluent`. Start the combined server
with:

```bash
cp config/config.fluent780.example.json config.fluent780.json   # set fluent.dry_run to false to drive the real instrument
uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json
```

## Architecture

```
SiLA 2 client (UniteLabs App, Python, etc.)
   │  jp.riken.bdr/{fluent,odtc,platereader}/*
   ▼
This connector (on the Fluent PC as the task OFML_Fluent780Server, or on another computer)
   │  SiLA 2: PrepareMethod / RunMethod / ExecuteCommand(XML)
   ▼
UniteLabs FluentControl connector (Fluent PC, Session 1)
   │  VisionX COM API
   ▼
FluentControl (method OFML_ApiHost) → device drivers (SiLA-ODTC, Magellan, RGA, ...) → devices
```

Each operation starts one FluentControl run (`OFML_ApiHost`), sends its statements or device macros, and ends the run
(unless a run was opened with `RunController.StartRun`, which later commands then share). Before anything is sent,
every FluentControl definition the XML uses (liquid classes, tips, labware, locations, the worktable, device macros) is
checked and recorded on the Fluent PC under `C:\Users\Tecan\OFML` (`io/definitions.py`).

Things that FluentControl does not return through its API are read on the Fluent PC (over SSH, or directly when the
connector runs there): the ODTC temperatures from the driver log, Magellan's ASC result files, FluentControl's own log
(what a Smart Command or worklist expanded into), and the deck cameras.

### Servers

The combined server (since 2026-10-15) is the one to use. It puts all Features on a single server with a single back
end that sends commands to FluentControl, and enforces **one operation at a time**: an operation on another device is
rejected with "Another operation is running (...)". `StatusController.CurrentOperation` shows what is running.

| Server | Port | `--app` | Example config |
|---|---|---|---|
| "Tecan Fluent 780" (combined) | 50060 | `unitelabs.tecan_fluent:create_app` | `config/config.fluent780.example.json`, `config/config.fluent780.fluentpc.example.json` (on the Fluent PC) |
| "Inheco ODTC (Fluent 780)" | 50061 | `unitelabs.tecan_fluent.apps.odtc:create_app` | `config/config.example.json` |
| "Tecan Infinite 200 PRO (Fluent 780)" | 50063 | `unitelabs.tecan_fluent.apps.infinite_fluent:create_app` | `config/config.infinite.example.json` |
| "Tecan Infinite 200 PRO (USB)" | 50065 | `unitelabs.tecan_fluent.apps.infinite_usb:create_usb_app` | `config/config.infinite_usb.example.json` |

The per-device servers (ODTC, Infinite) are still available, but **do not run them at the same time as the combined
server**: they do not know about each other's operations and could end someone else's run through the UniteLabs
connector's "last opened channel". The ODTC server and the Infinite server also each enforce "one operation at a time"
independently; do not send commands to both at the same time.

### Features

| Feature | Device | Servers |
|---|---|---|
| `RgaController`, `LabwareController` | RGA plate gripper, FluentControl's labware statements | combined |
| `LiquidHandling` | Air FCA pipetting arm | combined |
| `DoorController`, `MethodController`, `TemperatureController`, `StatusController` | Inheco ODTC 96 | combined, ODTC |
| `TrayController`, `AbsorbanceReader` | Infinite 200 PRO | combined, Infinite, USB |
| `FluentPlateHandling` | Infinite 200 PRO with the RGA | combined, Infinite |
| `BioShakeController`, `ShakingIncubatorController`, `TemperaturePositionController`, `Incubator1Controller` | temperature-controlled and shaking devices | combined |
| `ColorMixDemo` | pipetting and the reader together (hackathon demo) | combined |
| `DeckCamera` | the three deck-check cameras | combined |
| `RunController` | runs shared by several commands | combined |

Feature names and contents are the same in every server, so clients only need to change the address. Features for
newly added devices are prefixed with the device name (e.g. `BioShakeController`); the ODTC's `TemperatureController`
keeps its original name. The commands of each Feature are listed under [Usage](#usage).

### Package layout

```
src/unitelabs/tecan_fluent/
  __init__.py   create_app and Fluent780ConnectorConfig of the combined server (loaded on first use)
  __main__.py   python -m unitelabs.tecan_fluent
  apps/         server assemblies: fluent780.py (combined), odtc.py, infinite_fluent.py, infinite_usb.py
  features/     the SiLA Features (one per module) and their errors
  io/           FluentControl back end, definition checks and records, Fluent PC access, XML builders,
                the Infinite back ends, the deck camera driver, the labware position record
  data/         reference statements from the 01-07 GUI scripts and the ODTC method store copy
config/         example configurations
scripts/        extract_gui_macros.py, extract_gui_statements.py
scripts/windows/  PowerShell and Python scripts that run on the Fluent PC
tests/          features/, io/, apps/ and fixtures/
docs/           reference notes (docs/gui_statements.md)
```

The UniteLabs CDK assumes there is only one subclass of `ConnectorBaseConfig` in the process. Each server assembly has
its own config class, so only the app being started is imported (`unitelabs.tecan_fluent` loads the combined server
only when `create_app` is asked for).

### Quirks of the back end (UniteLabs FluentControl connector)

- **After restarting FluentControl, send `FluentController.GetRuntime` to the UniteLabs connector.** Otherwise it
  keeps pointing at the old FluentControl instance.
- On startup FluentControl stops at the "research use only" dialog (`VX_APPFR_019_001`). It can be closed with
  `RuntimeController.RespondToDialog(id, "OK")`.
- When a run finishes, FluentControl closes the method itself and enters `RunModeRunFinished`. This is an idle state;
  `CloseMethod` is not needed (and is rejected if sent).
- The UniteLabs connector is configured with port 0, so its port changes on every restart. When this connector cannot
  connect, it rediscovers only the port via mDNS (the other side advertises only `127.0.0.1` and `169.254.*` via mDNS,
  so the address comes from the `fluent.host` setting).

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12 is picked from `.python-version`).
- The UniteLabs FluentControl connector running on the Fluent PC (Session 1), and FluentControl with the method
  `OFML_ApiHost`.
- When this connector does not run on the Fluent PC itself: key-based `ssh Tecan@10.5.1.156` from the computer that
  runs it (definitions, records, temperatures, result files and cameras are read and written over SSH/scp).
- The Fluent PC scripts that the connector calls, in `C:\Users\Tecan\OFML\tools\`: `odtc_last_sensor_values.ps1`,
  `camera_shot.ps1` and `camera_videos.ps1` (from `scripts/windows/`).

### Installation

```bash
git clone https://github.com/ozatamago/riken-odtc-connector.git
cd riken-odtc-connector
uv sync
```

`uv sync` also installs pytest (the `test` extra, through the default `dev` group); `uv sync --all-extras` adds
the development tools (ruff, pre-commit, commitizen).

### Configuration

Copy an example from `config/` to the repository root and adjust it. The local configurations (`config.json`,
`config.fluent780.json`, `config.infinite.json`, `config.infinite_usb.json` and their `*.dryrun.json` variants) are
not in Git.

```bash
cp config/config.fluent780.example.json config.fluent780.json       # combined server
cp config/config.example.json config.json                           # ODTC server
cp config/config.infinite.example.json config.infinite.json         # Infinite server
cp config/config.infinite_usb.example.json config.infinite_usb.json # stand-alone USB Infinite
```

- With `fluent.dry_run: true`, the XML is built and logged but nothing is sent to the Fluent. `dry_run_seconds` adds
  a simulated wait. The USB Infinite has `reader.dry_run` instead.
- **Set `sila_server.hostname` to the LAN address (e.g. `10.5.1.213`).** With `0.0.0.0`, mDNS also advertises
  `127.0.0.1`, and the UniteLabs App on the Fluent PC ends up connecting to itself. If you do not want mDNS
  advertisement, set `discovery` to `null`.
- Only one server with the same UUID may run at a time.

### Starting

```bash
uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json
uv run connector start --app unitelabs.tecan_fluent.apps.odtc:create_app -cfg config.json
uv run connector start --app unitelabs.tecan_fluent.apps.infinite_fluent:create_app -cfg config.infinite.json
uv run connector start --app unitelabs.tecan_fluent.apps.infinite_usb:create_usb_app -cfg config.infinite_usb.json
```

The combined server can also be started with `uv run python -m unitelabs.tecan_fluent [config path]` (default
`config.fluent780.json`).

## Testing

```bash
uv run pytest
```

The tests connect to neither the devices nor the Fluent PC (`tests/conftest.py` replaces every SSH, file and camera
access). `tests/features/` tests the Features, `tests/io/` the back ends and XML builders, `tests/apps/` the server
assemblies; `tests/fixtures/` holds XML and files from the instrument. They check that the XML sent is identical,
character for character, to what succeeded on the instrument, that dangerous macros are rejected, that the method list
loads, the PreMethod pairing, and the checks before pipetting.

Device macro templates extracted from the GUI scripts (83 of them) are in `tests/fixtures/gui_macros/` (sources in
`index.tsv`; extracted with `scripts/extract_gui_macros.py`). The FluentControl statements of the 01-07 GUI scripts
are in `tests/fixtures/gui_statements/` (`scripts/extract_gui_statements.py`; see `docs/gui_statements.md`).

Lint and format checks (also run in CI, `.github/workflows/test.yml`):

```bash
uv run ruff check
uv run ruff format --check
```

## Deploying to the Fluent PC

The server runs on the Fluent PC (Windows) as the scheduled task `OFML_Fluent780Server`. With `ssh_target` set to
`"local"`, the commands that otherwise go over SSH/scp (definitions, records, cameras, FluentControl's log) run
directly.

```powershell
git clone https://github.com/ozatamago/riken-odtc-connector.git C:\Users\Tecan\OFML\connector
cd C:\Users\Tecan\OFML\connector
uv sync
copy config\config.fluent780.fluentpc.example.json config.fluent780.json   # hostname 10.5.1.156, ssh_target "local"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start_connector.ps1
```

- `scripts/windows/start_connector.ps1` starts `unitelabs.tecan_fluent:create_app` with
  `C:\Users\Tecan\OFML\connector\config.fluent780.json` and writes the server output to
  `C:\Users\Tecan\OFML\connector_state\server_<time>.log`.
- Only one server with the same UUID may run: stop it on the other computer first.
- Records that cannot be stored at once wait in `fluent.definitions.local_dir` (`C:\Users\Tecan\OFML\connector_state`).
- The labware positions the RGA commands remember are kept on the Fluent PC
  (`C:\Users\Tecan\OFML\state\labware_positions.json`, setting `plates.positions_file`).

### Scheduled task

A server started from an SSH session ends with it. Run it as the scheduled task `OFML_Fluent780Server`
(`scripts/windows/register_server_task.ps1`: the logged-on user, session 1, no password stored, starts at logon):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Tecan\OFML\connector\scripts\windows\register_server_task.ps1
schtasks /run /tn OFML_Fluent780Server    # start
schtasks /end /tn OFML_Fluent780Server    # stop (also stop the server processes if they remain)
```

The task runs the script at the path it was registered with. After an update that moves `start_connector.ps1`
(it moved from `windows\` to `scripts\windows\`), register the task again.

### SSH tunnel

Port 50060 is not opened in the firewall (the server is unencrypted and anyone who reaches it can move the robot).
Other computers use an SSH tunnel, together with the UniteLabs App's ports:

```bash
ssh -N -L '3000:[::1]:3000' -L 3004:localhost:3004 -L 50060:10.5.1.156:50060 Tecan@10.5.1.156
```

Then the server is `localhost:50060` and the App `http://localhost:3000`.

### Updating

Push from the development computer, then on the Fluent PC `git pull`, stop and start the task.

## Usage

Use the server from the UniteLabs App or any SiLA 2 client.

- When entering string values in the UniteLabs App, do not add quotes (the quotes become part of the value).
- After adding Commands, make the UniteLabs App reload the Features
  (`PATCH http://10.5.1.156:3004/api/servers/<UUID>/features/update`, or reload the page).
- **There is no authentication or encryption.** Anyone who reaches the server can move the instrument.

(P) marks a Property. All others are Commands; the Observable ones report progress and remaining time every 2 seconds.

### RGA (`RgaController`, combined server)

| Command / Property | Description |
|---|---|
| `LabwarePositions` (P) | Labware that may be moved, and the current position the connector remembers for each |
| `MoveLabware(Labware, Location, Site)` | Move to the given position (e.g. `Regrip_Pos`, 1 = the regrip position before loading into the reader) |
| `ReturnLabware(Labware)` | Return to the home position (the initial worktable position) |
| `RecordLabwarePosition(Labware, Location, Site)` | Tell the connector the current position after moving labware by hand (the instrument does not move) |

- FluentControl resets labware to its initial position at the start of every run, so the connector remembers the
  current position (on the Fluent PC, `C:\Users\Tecan\OFML\state\labware_positions.json`) and, at the start of the next
  run, syncs FluentControl with `RemoveLabware` → `AddLabware` before moving. If the Fluent PC cannot be reached, moves
  are refused; in a dry run, moves are remembered in memory only.
- Only labware listed in the `plates.labware` setting (name, type, home position) may be moved (default
  `96 Well Flat_Custom[001]`, home position `Nest7mm_Pos[6]`).
- **Verified on the instrument from the UniteLabs App on 2026-10-15**: `Nest7mm_Pos[6]` → `Regrip_Pos[1]` → back to
  `Nest7mm_Pos[6]` in a separate run.

### Temperature-controlled and shaking devices (combined server)

| Feature | Command | Range (as restricted by the connector) |
|---|---|---|
| `BioShakeController` | `SetTemperature(Temperature)` / `TemperatureOff` | 4–70 °C |
| | `LockPlate` / `UnlockPlate` | |
| | `ShakeOn(Speed)` / `ShakeOff` | 1000, 1200, 1400, 1600, 1800 or 2000 rpm |
| `ShakingIncubatorController` (Inheco Incubator Shaker DWP) | `SetTemperature(Temperature)` | 20–60 °C |
| | `Close` | |
| | `ShakeOn` / `ShakeOff` | fixed preset `14,1.0,14,1.0,180` |
| `TemperaturePositionController` (the 3 CPLC positions, inhecoMTC) | `SetTemperature(Slot, Temperature)` / `TurnOff(Slot)` | 4–70 °C, slots 1–3 |
| `Incubator1Controller` (6 Nest Incubator Shaking) | `SetTemperature(Temperature)` (all positions) | 20–50 °C |
| | `CloseDoor` | |
| | `StartShaker(Frequency)` / `StopShaker` | 1.0–8.5 Hz |

- Commands return as soon as they are sent (they do not wait for the temperature to be reached). On 2026-10-15 each
  took about 9 s on the instrument, and the driver logged SC_ERROR_NONE.
- BioShake lock/unlock/shake, Inheco close/shake and Incubator1 door/shaker (5 Hz) were verified on the instrument on
  2026-10-15 (no plate loaded; each shake ran for about 5 s).
- The basis for each argument's meaning, and the values whose meaning is unknown (fixed to the same values as the GUI
  scripts), are documented at the top of `src/unitelabs/tecan_fluent/features/temperature_devices.py`.
- Tecan's cleanup (Sub_Cleanup) returns the Inheco incubator and Incubator1 to 25 °C, sends TempOff to the BioShake,
  and turns the CPLC off.

### ODTC (combined server and ODTC server)

| Feature | Command / Property | Description | Verified on the instrument (2026-10-15) |
|---|---|---|---|
| `DoorController` | `OpenDoor` / `CloseDoor` | Open/close the door (drawer) | door motion 9–10 s, total 18–48 s |
| `MethodController` | `Methods` (P) | The 5 PreMethods and 7 Methods registered on the device, with estimated durations | reads the copy taken on 2026-08-10 |
| | `RunPreMethod(PreMethod)` | Preheat. 7 min 45 s regardless of target temperature | `ini25` 466.3 s, 467.5 s |
| | `RunMethod(Method)` | Temperature program. Requires the matching PreMethod immediately before | `test` 16.0 s |
| | `LastPreMethod` (P) | The last PreMethod this connector completed | |
| `TemperatureController` | `ReadTemperatures` | Block, lid and other temperatures (°C) | about 12 s |
| `StatusController` | `Ready` / `Busy` / `CurrentOperation` / `FluentControlState` / `ActiveDialogs` (P) | Whether a command can be accepted right now, and what is running | |

Only one ODTC operation can run at a time.

Safeguards:

- **Only macros that have succeeded on the instrument are sent** (`OpenDoor`, `CloseDoor`, `ExecuteMethod`,
  `ReadActualTemperature`). `SetParameters` crashes the ODTC (confirmed as a device-side bug), and `StopMethod` is
  rejected by FluentControl, so neither can be sent.
- **Tests check that the XML sent is identical, character for character, to the files that succeeded on the
  instrument** (`tests/fixtures/`).
- **A Method is accepted only if a PreMethod with the matching start block temperature was completed immediately
  before.** Each PreMethod is consumed by one Method. Pairs: `ini4`–HeatShock, `ini25`–test, `ini37`–EnzymeReaction,
  `ini42`–For * insert, `ini95`–PCR.
- If FluentControl is not idle (another run in progress, waiting on a dialog), the request is rejected without doing
  anything.

Known limitations:

- The method list is a copy taken from the device on 2026-08-10. Methods added to the device after that do not appear.
- `LastPreMethod` is lost when the connector restarts. It also does not know about PreMethods run from the
  FluentControl GUI.
- FluentControl does not return temperature values through the API, so **they are read from the driver log on the
  Fluent PC** (place `scripts/windows/odtc_last_sensor_values.ps1` in `C:\Users\Tecan\OFML\tools\`). A connector that
  does not run on the Fluent PC must be able to `ssh Tecan@10.5.1.156` with key authentication. The ODTC clock is in
  local time, but timestamps end in `Z`.
- While a Method such as PCR is running, neither temperatures nor the door can be operated (FluentControl runs only
  one run at a time).

### Infinite 200 PRO in the Fluent 780 (combined server and Infinite server)

The back end (FluentControl runs via the UniteLabs connector) is shared with the ODTC.

| Feature | Command / Property | Description |
|---|---|---|
| `TrayController` | `OpenTray` / `CloseTray` | Open/close the tray (`Magellan_Open` / `Magellan_Close`) |
| `AbsorbanceReader` | `Methods` (P) | Measurement files in `Magellan Pro\mth` on the Fluent PC |
| | `MeasureLoadedPlate(Method)` | Measure the plate already inside and return the values as labels × 96 wells |
| | `ReadAbsorbance(Wavelength)` | Return the OD of 96 wells at one wavelength. The Fluent version supports only wavelengths listed in the `infinite.wavelength_methods` setting |
| `FluentPlateHandling` | `MeasureWorktablePlate(Labware, Method)` | Move a plate registered on the worktable (by name) into the reader, measure it, and return it to its original position. One run |
| | `MeasurePlate(LabwareType, Location, Site, Method)` | Temporarily register an unregistered plate and do the same (**not verified on the instrument**) |

- Loading, measurement and unloading are done in a single run because FluentControl forgets labware positions when a
  new run starts (2026-08-13). `MeasurePlate` registers the plate under the temporary name `SiLA_ReaderPlate[001]` and
  deletes it afterwards. The source position must be empty in FluentControl's records.
- The regrip position is `Regrip_Pos[1]`, for flat-bottom plates. **PCR plates cannot be loaded into the reader with
  the current setup** (2026-10-09).
- Results are read from Magellan's ASC files (latin-1) on the Fluent PC. Both the grid format and the
  one-well-per-line format (row order A1, A2, ...) are supported.
- `Abs600.mth` has 37 °C incubation enabled.
- **Verified on the instrument on 2026-10-15**: `OpenTray` / `CloseTray` (12 s each),
  `MeasureWorktablePlate("96 Well Flat_Custom[001]", "OFML_Abs405.mth")` (311 s total, of which 254 s measuring,
  3 labels × 96 wells). Loading into and unloading from the reader worked with RGA macros (XML).

### Infinite 200 PRO stand-alone (USB server, PyLabRobot)

A server for an Infinite 200 PRO that is not built into a Fluent, connected by USB to a Mac or Linux PC.
**The `TrayController` and `AbsorbanceReader` definitions are identical to the Fluent version**, so callers can use
the same Commands. There is no `FluentPlateHandling`.

| Command | Behaviour in the USB version |
|---|---|
| `OpenTray` / `CloseTray` | PyLabRobot `open()` / `close(plate)` |
| `ReadAbsorbance(Wavelength)` | PyLabRobot `read_absorbance(plate, all wells, wavelength)`. 230–1000 nm |
| `MeasureLoadedPlate(Method)` / `Methods` | Not available (no Magellan). `Methods` is empty |

- The back end is PyLabRobot's `ExperimentalTecanInfinite200ProBackend` (experimental, M series only), pinned to
  commit `183cabd` on GitHub main (as of 2026-10-15). It is not in PyPI release 0.2.2.
- The default plate definition is `cor_96_wellplate_360uL_Fb` (Costar 96 Flat Transparent).
- **It cannot be used for the Infinite in the Fluent PC.** On the Fluent PC the reader is attached to Tecan's
  proprietary USB driver (`Tecanat_Usb`) and cannot be opened from pyusb.
- **Not verified on an instrument** (no standalone Infinite is connected). On 2026-10-15 it was checked with tests that
  replace the PyLabRobot back end with a fake, and with a dry run. It was confirmed that, with no reader attached, it
  fails with "USB device not found".

### Pipetting, labware, runs, cameras and the demo (combined server)

`LiquidHandling`, `LabwareController`, `RunController`, `DeckCamera` and `ColorMixDemo` describe their commands in
their Feature and Command descriptions (shown in the UniteLabs App); the background is in the module docstrings under
`src/unitelabs/tecan_fluent/features/` and `src/unitelabs/tecan_fluent/io/`.

## Contribute

Set up the development environment and the pre-commit hooks (ruff, ruff-format, commitizen and the standard checks):

```bash
uv sync --all-extras
uv run pre-commit install
```

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (checked by the commitizen
  hook; `uv run cz commit` helps write them). Note changes in `CHANGELOG.md`.
- Code, comments, docstrings and messages are in English. Feature, Command and parameter names and their docstrings
  are what clients see: changing them changes the SiLA Feature definitions.
- Development mode reloads the connector whenever the source changes:

  ```bash
  uv run connector dev --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json
  ```

## Contact

If you found a bug, please use the [issue tracker](https://github.com/ozatamago/riken-odtc-connector/issues).
