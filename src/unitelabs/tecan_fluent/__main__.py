"""Start the combined "Tecan Fluent 780 (All devices)" server: python -m unitelabs.tecan_fluent [config path].

The config path defaults to config.fluent780.json in the current folder. `uv run connector start --app
unitelabs.tecan_fluent:create_app -cfg <config path>` does the same and also sets up logging from the config.
"""

import asyncio
import pathlib
import sys

from unitelabs.cdk import ConnectorBaseConfig, run

from . import create_app


async def main() -> None:
    """Run the connector application."""

    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "config.fluent780.json")
    await run(create_app, config=ConnectorBaseConfig.load(path))


if __name__ == "__main__":
    asyncio.run(main())
