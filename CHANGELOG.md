# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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
