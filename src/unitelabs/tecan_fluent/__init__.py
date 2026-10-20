"""SiLA 2 connector for the RIKEN BDR Tecan Fluent 780, driven through FluentControl (UniteLabs CDK).

    uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json

create_app and Fluent780ConnectorConfig are the combined "Tecan Fluent 780" server (apps/fluent780_all.py). The other
server assemblies (ODTC only, Infinite only, stand-alone Infinite over USB) are in apps/.

The UniteLabs CDK assumes there is only one subclass of ConnectorBaseConfig in the process. Importing any module of
this package runs this file first, so the combined server's config class is imported only when it is asked for
(otherwise it would coexist with the config class of the other app being started).
"""

import importlib.metadata

__version__ = importlib.metadata.version("unitelabs-tecan-fluent")


def __getattr__(name):
    if name in ("create_app", "build_features", "Fluent780ConnectorConfig"):
        from .apps import fluent780_all

        return getattr(fluent780_all, name)
    raise AttributeError(name)
