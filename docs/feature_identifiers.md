# Feature identifiers: old -> new

The SiLA features were renamed so that the device comes first everywhere (docs/device_naming_spec.md). The commands,
properties, parameters, responses, errors and data types inside each feature did not change; only the category, the
identifier and the display name did. A client that calls a feature by its fully qualified identifier must use the new
one, e.g. `jp.riken.bdr/fluent/RunController/v1` -> `jp.riken.bdr/tecan.fluent/RunControl/v1`. In the UniteLabs App,
register the servers again: their feature lists changed.

All features keep the originator `jp.riken.bdr` and version 1.0 (`/v1`).

Incubator1's category is `tecan.incubator`, not `tecan.incubator1` as first planned: the SiLA feature definition
schema allows only lower-case letters and dots in a category, and SiLA clients refuse the server otherwise.

| Device | Old identifier | New identifier | Display name | Python class (module) |
|---|---|---|---|---|
| Fluent | `jp.riken.bdr/fluent/RunController/v1` | `jp.riken.bdr/tecan.fluent/RunControl/v1` | Fluent - Run (Start / End) | `RunControl` (`features/fluent/run_control.py`) |
| Fluent | `jp.riken.bdr/odtc/StatusController/v1` | `jp.riken.bdr/tecan.fluent/Status/v1` | Fluent - Status | `Status` (`features/fluent/status.py`) |
| FCA arm | `jp.riken.bdr/fluent/LiquidHandling/v1` | `jp.riken.bdr/tecan.fluent.arm/LiquidHandling/v1` | FCA Arm - Liquid Handling | `LiquidHandling` (`features/fluent/arm/liquid_handling.py`) |
| RGA gripper | `jp.riken.bdr/fluent/RgaController/v1` | `jp.riken.bdr/tecan.fluent.gripper/PlateTransfer/v1` | RGA Gripper - Move & Return Plate | `PlateTransfer` (`features/fluent/gripper/plate_transfer.py`) |
| RGA gripper | `jp.riken.bdr/fluent/LabwareController/v1` | `jp.riken.bdr/tecan.fluent.gripper/Labware/v1` | RGA Gripper - Labware, Lids & Fingers | `Labware` (`features/fluent/gripper/labware.py`) |
| Deck cameras | `jp.riken.bdr/fluent/DeckCamera/v1` | `jp.riken.bdr/tecan.fluent.camera/DeckCamera/v1` | Deck Cameras | `DeckCamera` (`features/fluent/camera/deck_camera.py`) |
| ODTC | `jp.riken.bdr/odtc/DoorController/v1` | `jp.riken.bdr/inheco.odtc/Door/v1` | ODTC - Door | `Door` (`features/odtc/door.py`) |
| ODTC | `jp.riken.bdr/odtc/MethodController/v1` | `jp.riken.bdr/inheco.odtc/Methods/v1` | ODTC - Temperature Programs | `Methods` (`features/odtc/methods.py`) |
| ODTC | `jp.riken.bdr/odtc/TemperatureController/v1` | `jp.riken.bdr/inheco.odtc/Temperatures/v1` | ODTC - Temperatures | `Temperatures` (`features/odtc/temperatures.py`) |
| Infinite | `jp.riken.bdr/platereader/TrayController/v1` | `jp.riken.bdr/tecan.infinite/Tray/v1` | Infinite - Tray | `Tray` (`features/infinite/tray.py`) |
| Infinite | `jp.riken.bdr/platereader/AbsorbanceReader/v1` | `jp.riken.bdr/tecan.infinite/Absorbance/v1` | Infinite - Absorbance | `Absorbance` (`features/infinite/absorbance.py`) |
| Infinite | `jp.riken.bdr/platereader/FluentPlateHandling/v1` | `jp.riken.bdr/tecan.infinite/PlateHandling/v1` | Infinite - Plate In / Out (RGA) | `PlateHandling` (`features/infinite/plate_handling.py`) |
| BioShake | `jp.riken.bdr/fluent/BioShakeController/v1` | `jp.riken.bdr/qinstruments.bioshake/BioShake/v1` | BioShake - Shake & Heat | `BioShake` (`features/bioshake/bioshake.py`) |
| Inheco incubator | `jp.riken.bdr/fluent/ShakingIncubatorController/v1` | `jp.riken.bdr/inheco.incubator/ShakingIncubator/v1` | Inheco Incubator - Shake & Heat | `ShakingIncubator` (`features/inheco_incubator/shaking_incubator.py`) |
| Inheco CPLC | `jp.riken.bdr/fluent/TemperaturePositionController/v1` | `jp.riken.bdr/inheco.cplc/CoolingHeatingPlates/v1` | Cooling / Heating Plates (CPLC 1-3) | `CoolingHeatingPlates` (`features/cplc/cooling_heating_plates.py`) |
| Incubator1 | `jp.riken.bdr/fluent/Incubator1Controller/v1` | `jp.riken.bdr/tecan.incubator/Incubator1/v1` | Incubator1 - Temperature, Shaker & Door | `Incubator1` (`features/incubator1/incubator1.py`) |
| Demo | `jp.riken.bdr/fluent/ColorMixDemo/v1` | `jp.riken.bdr/demo/ColorMix/v1` | Demo - Color Mix & Measure | `ColorMix` (`features/demo/colormix.py`) |

Features added later (no old identifier; served by `fluent780_all` and `fluent780`, docs/deck_state_spec.md and
docs/lab_capabilities_spec.md):

| Device | Identifier | Display name | Python class (module) |
|---|---|---|---|
| Fluent | `jp.riken.bdr/tecan.fluent/Deck/v1` | Fluent - Deck | `Deck` (`features/fluent/deck.py`) |
| Fluent | `jp.riken.bdr/tecan.fluent/HandsOff/v1` | Fluent - Hands Off | `HandsOff` (`features/fluent/hands_off.py`) |
| Fluent | `jp.riken.bdr/tecan.fluent/LabCapabilities/v1` | Fluent - Lab Capabilities | `LabCapabilities` (`features/fluent/lab_capabilities.py`) |

Descriptions that named another feature follow the new names, e.g. "RunController.StartRun" -> "RunControl.StartRun",
"AbsorbanceReader.Methods" -> "Absorbance.Methods", and the error message "Start a run first
(RunController.StartRun)" -> "(RunControl.StartRun)".

Other renames in the same change, for code that imports the package:

| Old | New |
|---|---|
| `unitelabs.tecan_fluent.apps.fluent780` (combined server), `Fluent780ConnectorConfig` | `unitelabs.tecan_fluent.apps.fluent780_all`, `Fluent780AllConnectorConfig` (`unitelabs.tecan_fluent:create_app` is unchanged) |
| `unitelabs.tecan_fluent.apps.infinite_fluent` | `unitelabs.tecan_fluent.apps.infinite` |
| `io.fluent_backend.FluentOdtcBackend` | `io.fluentcontrol.backend.FluentControlBackend` |
| server name "Tecan Fluent 780" (combined, port 50060) | "Tecan Fluent 780 (All devices)"; "Tecan Fluent 780" is now the Fluent-only server (port 50062) |
| server name "Tecan Infinite 200 PRO (Fluent 780)", UUID `9b4d2c1e-...` | "Tecan Infinite 200 PRO", UUID `371acb9a-2c10-4e34-9b05-ee7061522fc9` |
| USB reader port 50065 | 50069 (50065 is now the Inheco incubator server) |

The name `RunController` still appears in `io/fluentcontrol/backend.py`: there it is a feature of the UniteLabs
FluentControl connector (`RunController.ActiveDialogs`), not one of ours.
