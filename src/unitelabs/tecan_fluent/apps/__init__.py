"""Server assemblies (config class and create_app). Each has its own config class; start one per process.

    Combined "Tecan Fluent 780" server (also unitelabs.tecan_fluent:create_app):
        uv run connector start --app unitelabs.tecan_fluent.apps.fluent780:create_app -cfg config.fluent780.json
    ODTC only:
        uv run connector start --app unitelabs.tecan_fluent.apps.odtc:create_app -cfg config.json
    Infinite 200 PRO in the Fluent 780 (through FluentControl):
        uv run connector start --app unitelabs.tecan_fluent.apps.infinite_fluent:create_app -cfg config.infinite.json
    Stand-alone Infinite 200 PRO (USB, PyLabRobot):
        uv run connector start --app unitelabs.tecan_fluent.apps.infinite_usb:create_usb_app -cfg config.infinite_usb.json

The UniteLabs CDK assumes a single config class per process, so this package imports none of them.
"""
