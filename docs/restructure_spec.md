# Restructuring spec: follow the UniteLabs connector layout

Goal: bring this repository into the layout and conventions of the UniteLabs connector template
(`connector-factory`), as used by
[AccelerationConsortium/opentrons-ot2](https://github.com/AccelerationConsortium/opentrons-ot2) and
[AccelerationConsortium/opentrons-flex](https://github.com/AccelerationConsortium/opentrons-flex),
**without changing behaviour**. The server runs on the Fluent PC and is used from the UniteLabs App, so everything a
client sees must stay identical.

Work on a branch `restructure/unitelabs-layout`. Commit in small steps (one commit per phase below), Conventional
Commit messages (`refactor: ...`, `chore: ...`, `docs: ...`, `ci: ...`). Do not push, do not touch the Fluent PC.

## Must not change

- SiLA feature identifiers: class names, `originator`, `category`, `version`, command / property / parameter /
  response names and their docstrings (the docstrings are what the UniteLabs App shows).
- Server UUIDs, names, ports and every key of the JSON configuration files (the config schema).
- Paths on the Fluent PC (`C:\Users\Tecan\OFML\...`) and what the PowerShell scripts do.
- Test behaviour: before starting, `uv run pytest -q` passes 135 tests; afterwards the same tests (moved) must pass,
  none skipped that ran before.

## Target layout

```
src/unitelabs/tecan_fluent/
  __init__.py          Fluent780ConnectorConfig and create_app (today: fluent780.py); __version__ from metadata
  __main__.py          asyncio.run(main()) with unitelabs.cdk.run(create_app)
  apps/                the other server assemblies, unchanged in content
    odtc.py            (today: odtc_app.py)
    infinite_fluent.py (today: infinite/fluent_app.py)
    infinite_usb.py    (today: infinite/usb_app.py)
  features/            SiLA features only (one feature per file), plus their error classes
    door_controller.py method_controller.py temperature_controller.py status_controller.py run_controller.py
    rga_controller.py labware_controller.py liquid_handling.py deck_camera.py temperature_devices.py
    colormix_demo.py infinite.py (today: infinite/features.py)
  io/                  everything that talks to FluentControl, the Fluent PC or a device, no SiLA decorators
    fluent_backend.py definitions.py remote.py fc_log.py smart_xml.py method_store.py progress.py
    infinite/ (asc.py reader.py xml.py plr_reader.py)
  data/                the XML reference statements (unchanged)
config/                config.*.example.json (today in the repository root)
scripts/
  windows/             today: windows/*.ps1, *.py, *.vbs
  extract_gui_macros.py extract_gui_statements.py   (today: tools/)
tests/
  features/ io/ apps/  the existing tests, sorted by what they test
  fixtures/            unchanged
docs/                  unchanged (plus this spec)
```

Where a module mixes a feature and io code (e.g. `rga_controller.py` has `LabwareTracker` and `RgaController`,
`deck_camera.py` has the camera driver and the `DeckCamera` feature), split it: the io part goes to `io/`, the
feature part to `features/`. Keep import paths working inside the package only; no compatibility shims for the old
`riken_odtc_connector` name are needed except in `scripts/windows/start_connector.ps1`, which must start
`unitelabs.tecan_fluent:create_app` instead of `riken_odtc_connector.fluent780:create_app`.

Local configs that are not in Git (`config.json`, `config.fluent780.json`, `config.infinite.json`, `*.dryrun.json`)
stay where they are; only the `*.example.json` files move.

## Packaging

- Distribution name `unitelabs-tecan-fluent`, import name `unitelabs.tecan_fluent` (namespace package: no
  `src/unitelabs/__init__.py`).
- Build backend `hatchling`, `[tool.hatch.build.targets.wheel] packages = ["src/unitelabs"]`; make sure `data/*.xml`
  and `py.typed` are included.
- Keep the dependencies and versions exactly as today (`unitelabs-cdk~=0.13.6`, `sila2==0.14.0`, the pinned
  pylabrobot commit, `imageio-ffmpeg`). Update `uv.lock` with `uv lock` only as far as the rename requires.
- Optional groups as in the examples: `test` (pytest), `dev` (ruff, pre-commit, commitizen).

## Tooling (as in the examples)

- `ruff`: `line-length = 120`, `src = ["src", "tests"]`. Start with `select = ["F", "E", "W", "I", "UP", "B"]` and
  fix what it finds; do not enable the strict docstring rules (`D`, `DOC`, `ANN`) yet, they would force rewriting
  docstrings that the App shows. Run `ruff format` once.
- `.pre-commit-config.yaml`: ruff, ruff-format, commitizen, trailing-whitespace, end-of-file-fixer,
  check-added-large-files, check-toml, check-yaml, check-merge-conflict, detect-private-key.
- `[tool.commitizen]` with `cz_conventional_commits`, `tag_format = "v$version"`, `version_provider = "uv"`.
- `.editorconfig`, `CHANGELOG.md` (`# Changelog` / `## Unreleased` with one entry for this restructuring).
- `.github/workflows/test.yml`: on push and pull request to main, `uv sync --all-extras`, `ruff check`,
  `ruff format --check`, `pytest`.

## README

Same chapters as the examples: Architecture (how the server reaches FluentControl through the UniteLabs connector,
the features), Getting Started (Prerequisites, Installation), Testing, Deploying to the Fluent PC (scheduled task,
SSH tunnel), Usage, Contribute, Contact. Keep all the information the current README has; update every path.
English only (public repository).

## Done when

- `uv run pytest -q` passes the same 135 tests; `uv run ruff check` and `uv run ruff format --check` are clean.
- `uv run python -c "import unitelabs.tecan_fluent, unitelabs.tecan_fluent.apps.odtc"` works, and
  `uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config/config.fluent780.dryrun.example.json`
  (or the existing dry-run config) starts and lists the same features as before (compare the feature list printed
  by a SiLA client, or the registered feature classes, before and after).
- `git grep riken_odtc_connector` finds nothing outside CHANGELOG.md and this spec.
