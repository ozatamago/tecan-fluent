# Lab capabilities of the Fluent 780

`Fluent - Lab Capabilities` (`jp.riken.bdr/tecan.fluent/LabCapabilities/v1`) describes what this Fluent can hold and
do, so that a planning tool can survey several instruments of a lab (this Fluent, the Maholo robots ...) and compose a
protocol across them. It is read only: nothing moves and nothing in FluentControl changes.

## Where the description comes from

| Part | Source | Code |
|---|---|---|
| Places, labware types, tip types, liquid classes, RGA settings | The FluentControl database on the Fluent PC (`capabilities.database_root`, default `C:\ProgramData\Tecan\VisionX\DataBase`), read again at most every `capabilities.cache_s` seconds | `io/fluent/capabilities/database.py` |
| Arms, instruments, rules, notes | Kept in this connector, each with its basis | `io/fluent/capabilities/catalog.py` |
| Commands | The features of the same server, introspected (identifiers, parameters, docstrings) | `io/fluent/capabilities/commands.py` |
| Current state | The back end (busy, current operation, open run, holder of the shared lock) and the deck state | `features/fluent/lab_capabilities.py` |

The worktable described is `capabilities.worktable`, or the worktable of the definition checks
(`fluent.definitions.workspace`) when it is empty. Because the database is read directly, the server has to run on
the Fluent PC; elsewhere the database properties fail with `DatabaseUnavailable` and the catalog properties still
answer.

### How the database is read

- A worktable (`SystemSpecific\Worktable\Workspaces\*.xwsp`) is a tree: every site of a component points to a site
  template (`BaseTemplateGuid`) and holds a component or nothing.
- A place is a (location, site): the site template's `LocationGroupName`, numbered from 1 in file order per location,
  as FluentControl's scripts address it. Frame parts, grids and pins are left out.
- **Accepts**: the labware types that share a `WorktableConnector` reference with the place's site template.
- **GripperModes**: the robot paths of the site template for `CGA 1` (the RGA), limited to the carrier's
  `AllowedGripModes` for that site when it has them.
- **Pipetting**: yes when every carrier below the place has `ACCESSIBLE_FOR_LIHA` true, no when one has false,
  unknown otherwise.
- **Well volume**: computed from the well shapes filled to the top (the database has no nominal volume).
- **Liquid classes**: whether there is an `AirFca` part (the only part this arm uses), and per tip group of the AirFca
  equation sets the smallest and largest point of the `AdjustAccuracy` correction and whether it dispenses several
  times.

These are derived from the definitions; FluentControl's own checks were not compared with them (see `Notes`).

## Properties

| Property | Content |
|---|---|
| `Places` | Location, site, carrier, labware put there by the worktable, accepted labware types, gripper modes, pipetting |
| `LabwareTypes` | Labware types that fit some place: kind, wells, height, well volume, grip widths and force |
| `TipTypes` | FCA tip types: tip group, capacity, filter, racks on the worktable |
| `LiquidClasses` | Name, AirFca part, volume range per tip group |
| `Arms` | Air FCA 1 and RGA 1 with their ranges |
| `Instruments` | Instruments of the deck: whether on the worktable, locations, driver, connection, SiLA servers and features |
| `Commands` | Every command of this server with its parameters and description |
| `Constraints` | Rules a plan must follow, with category and basis (`definition`, `connector`, `observed`, `inference`) |
| `Notes` | How far the description can be trusted |
| `CurrentStateJson` | Busy, current operation, open run, other server holding FluentControl, deck state |
| `CapabilitiesJson` | All of the above as one JSON document, schema `riken-fluent-capabilities/1` |

## Configuration

```json
"capabilities": {
  "database_root": "C:\\ProgramData\\Tecan\\VisionX\\DataBase",
  "worktable": "",
  "cache_s": 600
}
```

The feature is served by `fluent780_all` and `fluent780`.
