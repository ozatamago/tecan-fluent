# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- A lock shared by every server on the Fluent PC (`fluent.shared_lock`), so that only one server at a time sends to
  FluentControl or keeps a run open; others are refused with the name of the holder, and `Fluent - Status` shows it.

### Added

- One server per device next to the combined one (`apps/<app>.py`, each with its own config class, fixed UUID and
  port): `fluent780` (the Fluent itself, 50062), `infinite` (50063, now with `Status`), `bioshake` (50064),
  `inheco_incubator` (50065), `cplc` (50066), `incubator1` (50067) and `colormix_demo` (50068), with
  `config/<app>.fluentpc.example.json` for the Fluent PC (each with its own `definitions.local_dir`).
  `scripts/windows/start_connector.ps1` and `register_server_task.ps1` take `-App` and `-Config` (task
  `OFML_<App>Server`); without parameters they still start and register the combined server as
  `OFML_Fluent780Server`.
- Tests that every app serves exactly the feature identifiers and display names of the table, and that every example
  config loads with unique UUIDs and ports.

### Changed

- **Breaking: feature identifiers are device first** (`docs/device_naming_spec.md`). Every feature sets its category,
  identifier and display name explicitly, e.g. `jp.riken.bdr/fluent/RunController/v1` ->
  `jp.riken.bdr/tecan.fluent/RunControl/v1` "Fluent - Run (Start / End)". The full old -> new table is in
  [docs/feature_identifiers.md](docs/feature_identifiers.md). Commands, properties, parameters, responses, errors
  and the XML sent to FluentControl are unchanged; servers must be registered again in the UniteLabs App.
- The combined server is `apps/fluent780_all.py` ("Tecan Fluent 780 (All devices)", same UUID and port 50060,
  config class `Fluent780AllConnectorConfig`); `unitelabs.tecan_fluent:create_app` is unchanged. The Infinite server
  is `apps/infinite.py` with a new UUID; the USB reader moved to port 50069. `FluentOdtcBackend` is now
  `FluentControlBackend`.
- `features/`, `io/` and `tests/` have one folder per device; the XML builders moved from the feature modules into
  `io/` (which removes the import of a feature module from `io/`).

### Fixed

- Refuse a command before PrepareMethod while FluentControl shows a dialog (e.g. "a door was opened" after a
  stopped run): FluentControl stays in RunModeRunFinished then, refuses PrepareMethod, and the UniteLabs connector did
  not answer for 2 minutes. `StatusController.Ready` ignores the empty "Unused ID" dialog left after a restart.

### Changed

- Restructured the repository into the UniteLabs connector layout: the package `riken_odtc_connector` is now the
  namespace package `unitelabs.tecan_fluent` (distribution `unitelabs-tecan-fluent`, built with hatchling), split
  into `features/` (SiLA features), `io/` (FluentControl, Fluent PC and device access) and `apps/` (the ODTC-only,
  Infinite-only and USB Infinite server assemblies). The combined server is started with
  `--app unitelabs.tecan_fluent:create_app`. Example configs moved to `config/`, the Windows scripts to
  `scripts/windows/`, the extraction tools to `scripts/`, and the tests into `tests/features`, `tests/io` and
  `tests/apps`. Added ruff, pre-commit, commitizen, `.editorconfig` and a GitHub Actions test workflow. SiLA
  features, server identities and the configuration schema are unchanged.
